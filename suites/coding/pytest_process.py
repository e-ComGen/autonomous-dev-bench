"""Container-only trusted pytest launcher. No model-facing evaluator endpoint."""
from pathlib import Path
import json
import os
import subprocess
import sys


def main():
    request = json.loads(Path("/input/checks.json").read_text())
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "HOME", "TMPDIR", "PYTHONPATH", "PYTHONUTF8"}}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTEST_ADDOPTS="")
    python = "/opt/project/bin/python"
    result = subprocess.run([python, "-B", "-m", "pytest", "-q", "--tb=short", "-o", "addopts=",
                             "-o", "cache_dir=/tmp/pytest-cache", "--junitxml=/results/tests.xml",
                             *request["paths"]], cwd="/workspace", env=environment,
                            stdin=subprocess.DEVNULL, timeout=request["seconds"], check=False)
    Path("/results/exit.json").write_text(json.dumps({"returncode": result.returncode}))
    return 0 if result.returncode in {0, 1} else 2


if __name__ == "__main__":
    raise SystemExit(main())
