"""Acquire prerequisites for the selected execution backend, then run the same issue A/B."""
import base64
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import load_launch_settings
from suites.coding.backend import backend_name
ADCP_REPOSITORY = "https://github.com/e-ComGen/autonomous-dev-control-plane.git"
from suites.coding.adcp_loading import ADCP_COMMIT


def selected_backend(arguments):
    return backend_name(load_launch_settings(ROOT, arguments))


def clean_acquisition_environment():
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, PYTHONUTF8="1")
    return result


def run_checked(argv, directory, environment, seconds):
    completed = subprocess.run(argv, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=seconds,
                               text=True, encoding="utf-8", errors="replace", shell=False)
    if completed.returncode:
        raise RuntimeError(f"Runtime preparation failed: {Path(argv[0]).name}, exit {completed.returncode}")


def read_token():
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise RuntimeError("GITHUB_TOKEN is required for GitHub issue discovery and private ADCP acquisition")
    return getpass.getpass("GitHub read token (hidden; not saved): ").strip()


def prepare_runtime():
    from tools.runtime_install import ensure_runtime
    ensure_runtime(ROOT, read_token, clean_acquisition_environment, run_checked)


def main():
    arguments = sys.argv[1:]
    command = arguments[0] if arguments and not arguments[0].startswith("-") else "ab"
    original = os.environ.get("GITHUB_TOKEN")
    try:
        if command in {"ab", "ab-preflight", "qualify"}:
            if sys.version_info < (3, 12):
                raise RuntimeError("Python 3.12 or newer is required")
            if "--offline" in arguments:
                raise RuntimeError("Issue A/B is not an offline self-test")
            selected = selected_backend(arguments)
            print("Selected backend: " + selected, flush=True)
            if selected == "docker" and not shutil.which("docker"):
                raise RuntimeError("Docker was explicitly selected but is unavailable; use --backend native --allow-local-execution")
            if "--replay" not in arguments or not (ROOT / ".bench/adcp/SOURCE.json").is_file():
                os.environ["GITHUB_TOKEN"] = read_token()
            if command != "qualify":
                prepare_runtime()
        return subprocess.call([sys.executable, "-I", str(ROOT / "tools/launch.py"), *arguments], cwd=ROOT)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        if original is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = original


if __name__ == "__main__":
    raise SystemExit(main())
