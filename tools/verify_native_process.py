"""Actual SDK boot and session in native processes on Windows/Linux; no paid model."""
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import json
import os
import runpy
import sys
import tempfile
import threading
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.backends.native import NativeRuntime
from suites.coding.native import NativeDriver


def main():
    evidence = ROOT / "artifacts"
    evidence.mkdir(exist_ok=True)
    settings = replace(Settings(), execution_backend="native", arm_seconds=120)
    with tempfile.TemporaryDirectory(prefix="native-") as temporary:
        runtime = NativeRuntime(ROOT, Path(temporary), settings)
        provider = None
        try:
            image = runtime.prepare_image()
            boot, _ = NativeDriver(runtime, runtime.scratch / "boot", settings, "no-provider").invoke(
                {"source.py": "VALUE = 1\n"}, "", boot_only=True)
            fixture = runpy.run_path(str(ROOT / "tests/coding/native_fixture_provider.py"))
            provider = ThreadingHTTPServer(("127.0.0.1", 0), fixture["Handler"])
            provider.request_path = evidence / "native-request.json"
            thread = threading.Thread(target=provider.serve_forever, daemon=True)
            thread.start()
            # Explicit TEST provider injection at the transport boundary; no production fallback.
            runtime.relay = SimpleNamespace(endpoint=lambda token: f"http://127.0.0.1:{provider.server_port}/fixture", close=lambda: None)
            returned, candidate = NativeDriver(runtime, runtime.scratch / "session", settings, "fixture").invoke(
                {"source.py": "VALUE = 1\n"}, "Reply with native-transport-ok.")
            if returned["text"].strip() != "native-transport-ok" or returned["finish_reason"] != "completed":
                raise ValueError("Native SDK fixture roundtrip failed: " + repr(returned))
            if candidate != {"source.py": "VALUE = 1\n"}:
                raise ValueError("Fixture unexpectedly changed source")
            result = {"platform": sys.platform, "python": sys.version, "backend": "native", "docker_invoked": False,
                      "sdk_boot": boot, "sdk_session": "RETURNED", "fixture_provider": True,
                      "paid_model_called": False, "image": image}
            (evidence / "native-process.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            if provider:
                provider.shutdown()
                provider.server_close()
            for index, path in enumerate(runtime.scratch.rglob("process.log")):
                text = path.read_text(encoding="utf-8", errors="replace")[-16000:]
                (evidence / f"native-process-{index}.log").write_text(text, encoding="utf-8")
                print(text)
            runtime.close()


if __name__ == "__main__":
    main()
