"""Trusted pytest launcher with explicit portable worker paths, never model PASS."""
from pathlib import Path
import json
import os
import subprocess
import sys


def main():
    inputs = Path(os.environ.get("AUTOBENCH_INPUT", "/input"))
    outputs = Path(os.environ.get("AUTOBENCH_RESULTS", "/results"))
    workspace = Path(os.environ.get("AUTOBENCH_WORKSPACE", "/workspace"))
    scratch = Path(os.environ.get("AUTOBENCH_SCRATCH", "/tmp"))
    request = json.loads((inputs / "checks.json").read_text(encoding="utf-8"))
    allowed = {"PATH", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "COMSPEC",
               "PATHEXT", "PYTHONPATH", "PYTHONUTF8", "APPDATA", "LOCALAPPDATA"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTEST_ADDOPTS="")
    python = os.environ.get("AUTOBENCH_PROJECT_PYTHON", "/opt/project/bin/python")
    result = subprocess.run([python, "-B", "-m", "pytest", "-q", "--tb=short", "-o", "addopts=",
                             "-o", "cache_dir=" + str(scratch / "pytest-cache"), "--junitxml=" + str(outputs / "tests.xml"),
                             *request["paths"]], cwd=workspace, env=environment,
                            stdin=subprocess.DEVNULL, timeout=request["seconds"], check=False)
    (outputs / "exit.json").write_text(json.dumps({"returncode": result.returncode}), encoding="utf-8")
    return 0 if result.returncode in {0, 1} else 2


if __name__ == "__main__":
    raise SystemExit(main())
