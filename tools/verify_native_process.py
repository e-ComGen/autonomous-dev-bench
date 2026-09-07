"""Actual SDK boot, streaming and real native tool effects; TEST provider only, no paid model."""
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import sys
import tempfile
import threading
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.backends.native import NativeRuntime
from suites.coding.native import NativeDriver


def fixture_server(path):
    definitions = runpy.run_path(str(path))
    handler = definitions.get("ToolHandler", definitions.get("Handler"))
    provider = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    provider.requests, provider.error, provider.selected_tool = 0, None, None
    provider.request_path = ROOT / "artifacts/native-request.json"
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    return provider


def main():
    evidence = ROOT / "artifacts"
    evidence.mkdir(exist_ok=True)
    settings = replace(Settings(), execution_backend="native", arm_seconds=120)
    with tempfile.TemporaryDirectory(prefix="native-") as temporary:
        runtime = NativeRuntime(ROOT, Path(temporary), settings)
        providers = []
        try:
            image = runtime.prepare_image()
            boot, _ = NativeDriver(runtime, runtime.scratch / "boot", settings, "no-provider").invoke(
                {"source.py": "VALUE = 1\n"}, "", boot_only=True)
            provider = fixture_server(ROOT / "tests/coding/native_fixture_provider.py")
            providers.append(provider)
            runtime.relay = SimpleNamespace(endpoint=lambda token: f"http://127.0.0.1:{provider.server_port}/fixture", close=lambda: None)
            returned, candidate = NativeDriver(runtime, runtime.scratch / "session", settings, "fixture").invoke(
                {"source.py": "VALUE = 1\n"}, "Reply with native-transport-ok.")
            if returned["text"].strip() != "native-transport-ok" or returned["finish_reason"] != "completed":
                raise ValueError("Native SDK fixture roundtrip failed: " + repr(returned))
            if candidate != {"source.py": "VALUE = 1\n"}:
                raise ValueError("Transport fixture unexpectedly changed source")
            provider = fixture_server(ROOT / "tests/native/tool_fixture.py")
            providers.append(provider)
            runtime.relay = SimpleNamespace(endpoint=lambda token: f"http://127.0.0.1:{provider.server_port}/fixture", close=lambda: None)
            tool_result, changed = NativeDriver(runtime, runtime.scratch / "tool", settings, "fixture").invoke(
                {"source.py": "VALUE = 1\n"}, "Use a shell tool to set source.py to VALUE = 2, then finish.")
            if changed != {"source.py": "VALUE = 2\n"} or tool_result["finish_reason"] != "completed":
                raise ValueError("The real DSH native tool did not produce its required filesystem effect")
            result = {"platform": sys.platform, "python": sys.version, "backend": "native", "docker_invoked": False,
                      "sdk_boot": boot, "sdk_session": "RETURNED", "fixture_provider": True,
                      "actual_tool_effect": "source.py changed to VALUE = 2", "tool": provider.selected_tool,
                      "paid_model_called": False, "image": image}
            (evidence / "native-process.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            for provider in providers:
                provider.shutdown()
                provider.server_close()
                if getattr(provider, "last_request", None):
                    (evidence / "native-tool-request.json").write_text(json.dumps(provider.last_request, indent=2), encoding="utf-8")
                    print("Fixture tool:", provider.selected_tool, "fixture error:", provider.error)
                    print("Tool results:", [msg for msg in provider.last_request["messages"] if msg.get("role") == "tool"])
            for index, path in enumerate(runtime.scratch.rglob("process.log")):
                text = path.read_text(encoding="utf-8", errors="replace")[-16000:]
                (evidence / f"native-process-{index}.log").write_text(text, encoding="utf-8")
                print(text)
            runtime.close()


if __name__ == "__main__":
    main()
