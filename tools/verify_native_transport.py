"""Real native SDK session against a TEST-ONLY HTTP fixture, not paid model evidence."""
from pathlib import Path
from dataclasses import replace
import json
import sys
import tempfile
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.docker_runtime import DockerRuntime
from suites.coding.native import NativeDriver


def main():
    settings = replace(Settings(), arm_seconds=90)
    with tempfile.TemporaryDirectory(prefix="transport-") as temporary:
        scratch = Path(temporary)
        runtime = DockerRuntime(ROOT, scratch, settings)
        try:
            image = runtime.prepare_image()
            runtime.command(("network", "create", "--internal", runtime.network))
            runtime.network_created = True
            results = scratch / "provider-results"
            results.mkdir()
            name = runtime.prefix + "-fixture"
            args = runtime.isolated_args(name, runtime.network) + ["-d", "--network-alias", "model-relay"]
            args += runtime.mount(ROOT / "tests/coding/native_fixture_provider.py", "/fixture.py", True)
            args += runtime.mount(results, "/results")
            runtime.containers.add(name)
            runtime.command((*args, runtime.image, "/fixture.py"))
            for _ in range(10):
                probe = runtime.command(("exec", name, "python", "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=1).read()"), 3, required=False)
                if probe.succeeded:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Test fixture did not start")
            driver = NativeDriver(runtime, scratch / "native", settings, "fixture")
            returned, _ = driver.invoke({"source.py": "VALUE = 1\n"}, "Reply with native-transport-ok.")
            if returned["text"].strip() != "native-transport-ok" or returned["finish_reason"] != "completed":
                raise ValueError("Native SDK did not complete the fixture response: " + repr(returned))
            request = json.loads((results / "request.json").read_text())
            if request["model"] != settings.model or request["message_count"] < 1:
                raise ValueError("Native provider request did not match model/input")
            output = ROOT / "artifacts/native-transport.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps({"status": "NATIVE_TRANSPORT_CHECKED", "image": image,
                "fixture_provider": True, "paid_provider_contacted": False,
                "finish_reason": returned["finish_reason"], "request": request}, indent=2))
            print("Native SDK session completed with TEST fixture; no paid provider contacted")
        finally:
            for path in runtime.scratch.rglob("process.log"):
                print(path.read_text(encoding="utf-8", errors="replace")[-12000:])
            runtime.close()


if __name__ == "__main__":
    main()
