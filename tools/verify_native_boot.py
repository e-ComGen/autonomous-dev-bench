"""CI/operator acceptance for the actual bundled DSH, without a model request."""
from pathlib import Path
import json
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.docker_runtime import DockerRuntime
from suites.coding.native import NativeDriver


def main():
    with tempfile.TemporaryDirectory(prefix="native-") as temporary:
        runtime = DockerRuntime(ROOT, Path(temporary), Settings())
        try:
            image = runtime.prepare_image()
            receipt, _ = NativeDriver(runtime, Path(temporary) / "boot", Settings(), "no-model").invoke(
                {"source.py": "VALUE = 1\n"}, "", boot_only=True)
            if receipt != {"status": "BOOTED", "model_called": False}:
                raise ValueError("Native boot did not complete")
            output = ROOT / "artifacts/native-boot.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps({"image": image, "receipt": receipt}, indent=2))
            print(json.dumps(receipt))
        finally:
            for path in runtime.scratch.rglob("process.log"):
                print(path.read_text(encoding="utf-8", errors="replace")[-10000:])
            runtime.close()


if __name__ == "__main__":
    main()
