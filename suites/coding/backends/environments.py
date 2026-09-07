"""Content-bound native dependency assets, analogous to runtime image artifacts."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import time
from benchmark_core.identity import canonical_json, Sha256Digest
from cli.oneclick.report import atomic_write
from .environment import interpreter_identity, wheel_manifest, verify_wheels, python_path
from .provision import Provisioner


class NativeEnvironments:
    def __init__(self, root, provision=None):
        self.root = Path(root).resolve() / ".bench/native"
        if self.root.is_symlink():
            raise ValueError("Native state must not be a link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.provision = provision or Provisioner()
        self.sdk_python = None
        self.sdk_id = None

    def store(self, kind, directory, wheels, extra=None):
        relative = Path(directory).resolve().relative_to(self.root).as_posix()
        value = {"schema": "autobench.native_environment/v1", "kind": kind, "directory": relative,
                 "python": interpreter_identity(), "wheels": wheels, **(extra or {})}
        identity = "native:" + str(Sha256Digest.of(value))
        target = self.root / "manifests" / (identity.rsplit(":", 1)[1] + ".json")
        atomic_write(target, canonical_json(value))
        return identity

    def load(self, identity):
        if not isinstance(identity, str) or not identity.startswith("native:sha256:"):
            raise ValueError("REPLAY_BACKEND_MISMATCH")
        key = identity.split(":")[-1]
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise ValueError("Invalid native environment identity")
        value = json.loads((self.root / "manifests" / (key + ".json")).read_text(encoding="utf-8"))
        if "native:" + str(Sha256Digest.of(value)) != identity or value["python"] != interpreter_identity():
            raise ValueError("NATIVE_ENVIRONMENT_IDENTITY_CHANGED")
        directory = (self.root / value["directory"]).resolve()
        if not directory.is_relative_to(self.root):
            raise ValueError("Unsafe native environment path")
        verify_wheels(directory / "wheels", value["wheels"])
        return directory, value

    def prepare_sdk(self, requirements):
        fingerprint = str(Sha256Digest.of({"python": interpreter_identity(),
            "requirements": Path(requirements).read_text(encoding="utf-8")})).split(":")[-1]
        ready = self.root / ("sdk-" + fingerprint[:16] + ".json")
        if ready.is_file():
            identity = json.loads(ready.read_text())["environment"]
            directory, _ = self.load(identity)
            python = python_path(directory / "venv")
            if python.is_file():
                self.sdk_python, self.sdk_id = python, identity
                return identity
            raise ValueError("NATIVE_SDK_INCOMPLETE; remove only its cached sdk directory and retry")
        directory = Path(tempfile.mkdtemp(prefix="sdk-", dir=self.root))
        deadline = time.monotonic() + 600
        print("Installing private Windows/native DSH dependencies...", flush=True)
        python = self.provision.venv(directory / "venv", deadline)
        self.provision.pip(python, ("download", "--only-binary=:all:", "--dest", directory / "wheels",
                                   "-r", Path(requirements).resolve()), directory, deadline)
        wheels = wheel_manifest(directory / "wheels")
        verify_wheels(directory / "wheels", wheels)
        self.provision.pip(python, ("install", "--no-index", "--no-deps",
            *[directory / "wheels" / name for name in sorted(wheels)]), directory, deadline)
        identity = self.store("sdk", directory, wheels)
        atomic_write(ready, json.dumps({"environment": identity}))
        self.sdk_python, self.sdk_id = python, identity
        return identity

    def execution_python(self, identity, directory, deadline):
        source, metadata = self.load(identity)
        if metadata["kind"] == "sdk":
            return self.sdk_python
        # Every agent/verification invocation gets a fresh environment from identical wheels.
        return self.provision.install_wheels(source / "wheels", metadata["wheels"],
                                             Path(directory) / "project-env", deadline)
