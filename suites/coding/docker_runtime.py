"""Bounded Docker commands through the existing ProcessRunner; no resident scheduler."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import time
from uuid import uuid4

from benchmark_core.execution import CommandSpec, ProcessRunner


class DockerRuntime:
    def __init__(self, root, scratch, settings):
        self.root, self.scratch, self.settings = Path(root), Path(scratch), settings
        self.runner = ProcessRunner()
        self.prefix = "adb-" + uuid4().hex[:12]
        self.network = self.prefix + "-internal"
        self.containers = set()
        self.network_created = False
        self.image = None

    def command(self, arguments, timeout=60, *, required=True):
        result = self.runner.run(CommandSpec(("docker", *map(str, arguments)), timeout))
        if required and not result.succeeded:
            raise RuntimeError("DOCKER_COMMAND_FAILED: " + result.stderr[-1500:])
        return result

    def prepare_image(self):
        server = self.command(("info", "--format", "{{.OSType}}"), 30).stdout.strip()
        if server != "linux":
            raise RuntimeError("Docker must be running with Linux containers")
        source = self.root / "suites/coding"
        context = self.scratch / "image"
        context.mkdir()
        for name in ("Dockerfile", "requirements.txt"):
            shutil.copyfile(source / "images" / name, context / name)
        shutil.copyfile(source / "native_driver.py", context / "native_driver.py")
        shutil.copytree(source / "provider", context / "provider", ignore=shutil.ignore_patterns("__pycache__"))
        fingerprint = hashlib.sha256()
        for path in sorted(context.rglob("*")):
            if path.is_file():
                fingerprint.update(path.relative_to(context).as_posix().encode() + b"\0" + path.read_bytes())
        tag = "autobenchmark-dsh:" + fingerprint.hexdigest()[:20]
        probe = self.command(("image", "inspect", tag, "--format", "{{.Id}}"), required=False)
        if not probe.succeeded:
            print("Preparing the pinned DSH container image...", flush=True)
            build = self.command(("build", "--label", "autobenchmark.input=" + fingerprint.hexdigest(),
                                  "-t", tag, context), 900, required=False)
            (self.scratch / "image-build.log").write_text(build.stdout[-65536:] + build.stderr[-65536:])
            if not build.succeeded:
                raise RuntimeError("DSH_IMAGE_BUILD_FAILED; inspect image-build.log")
        actual = self.command(("image", "inspect", tag, "--format", "{{.Id}} {{index .Config.Labels \"autobenchmark.input\"}}"))
        image, label = actual.stdout.strip().split()
        if label != fingerprint.hexdigest():
            raise RuntimeError("Container image label conflicts with the pinned build inputs")
        self.image = image
        return {"image_id": image, "build_input": fingerprint.hexdigest(), "sdk": "0.1.2rc1", "profile": "sdk"}

    def isolated_args(self, name, network):
        user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000"
        return ["run", "--name", name, "--network", network, "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=256", "--user", user,
                "--memory", str(self.settings.memory_mb) + "m", "--cpus", str(self.settings.cpus),
                "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m"]

    @staticmethod
    def mount(source, target, readonly=False):
        source = str(Path(source).resolve())
        if "," in source:
            raise ValueError("Docker bind source paths containing commas are unsupported")
        return ["--mount", f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")]

    def run(self, directory, *, network="none", entrypoint, timeout, input_path=None, evaluator=None):
        directory = Path(directory)
        results = directory / "results"
        results.mkdir(exist_ok=True)
        name = self.prefix + "-" + uuid4().hex[:10]
        args = self.isolated_args(name, network)
        args += self.mount(directory / "workspace", "/workspace") + self.mount(results, "/results")
        if input_path is not None:
            args += self.mount(input_path, "/input", True)
        if evaluator is not None:
            args += self.mount(evaluator, "/evaluator", True)
        self.containers.add(name)
        try:
            execution = self.command((*args, self.image, *entrypoint), timeout, required=False)
            (directory / "process.log").write_text(execution.stdout[-32768:] + execution.stderr[-32768:], encoding="utf-8")
            return execution
        finally:
            self.command(("rm", "-f", name), required=False)
            self.containers.discard(name)

    def start_relay(self, tokens):
        self.command(("network", "create", "--internal", self.network))
        self.network_created = True
        directory = self.scratch / "relay"
        directory.mkdir()
        results = directory / "results"
        results.mkdir()
        configuration = {"tokens": tokens, "model": self.settings.model,
                         "requests_per_arm": self.settings.requests_per_arm,
                         "output_tokens_per_request": self.settings.output_tokens_per_request,
                         "request_bytes": self.settings.request_bytes}
        (directory / "config.json").write_text(json.dumps(configuration))
        name = self.prefix + "-relay"
        self.containers.add(name)
        args = self.isolated_args(name, "bridge") + ["-d", "-e", "DEEPSEEK_API_KEY"]
        args += self.mount(directory / "config.json", "/config.json", True) + self.mount(results, "/results")
        self.command((*args, self.image, "/provider/server.py", "/config.json"))
        self.command(("network", "connect", "--alias", "model-relay", self.network, name))
        for _ in range(15):
            probe = self.command(("exec", name, "python", "-c",
                                  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=1).read()"),
                                 5, required=False)
            if probe.succeeded:
                return results / "provider.json"
            time.sleep(1)
        raise RuntimeError("MODEL_RELAY_NOT_READY")

    def close(self):
        for name in tuple(self.containers):
            self.command(("rm", "-f", name), required=False)
        if self.network_created:
            self.command(("network", "rm", self.network), required=False)
