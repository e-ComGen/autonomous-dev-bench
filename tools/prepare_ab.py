"""Acquire prerequisites for the selected execution backend, then run the same issue A/B."""
import argparse
import base64
from dataclasses import replace
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import load_settings
from suites.coding.backend import backend_name
ADCP_REPOSITORY = "https://github.com/e-ComGen/autonomous-dev-control-plane.git"
ADCP_COMMIT = "b9c933bd7727b86149da891c323a27cde5afc956"


def selected_backend(arguments):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--backend", choices=("auto", "native", "docker"))
    parser.add_argument("--ab-config", default=str(ROOT / "AB.toml"))
    known, _ = parser.parse_known_args(arguments)
    settings = load_settings(known.ab_config)
    return backend_name(replace(settings, execution_backend=known.backend or settings.execution_backend))


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
    target = ROOT / ".bench/adcp"
    if target.is_symlink() or (ROOT / ".bench").is_symlink():
        raise RuntimeError("Runtime storage must not be a symlink")
    if (target / "SOURCE.json").is_file():
        return
    if not shutil.which("git"):
        raise RuntimeError("Install Git before preparing ADCP")
    token = read_token()
    environment = clean_acquisition_environment()
    environment["AUTOBENCH_GIT_AUTH"] = "AUTHORIZATION: basic " + base64.b64encode(("x-access-token:" + token).encode()).decode("ascii")
    with tempfile.TemporaryDirectory(prefix="adb-source-") as temporary:
        checkout = Path(temporary)
        run_checked(["git", "-c", "core.longpaths=true", "init", "--quiet"], checkout, environment, 30)
        command = ["git", "--config-env=http.https://github.com/.extraheader=AUTOBENCH_GIT_AUTH",
                   "-c", "credential.helper=", "-c", "http.followRedirects=false", "-c", "core.longpaths=true",
                   "fetch", "--quiet", "--depth=1", "--no-tags", ADCP_REPOSITORY, ADCP_COMMIT]
        try:
            run_checked(command, checkout, environment, 300)
        finally:
            environment.pop("AUTOBENCH_GIT_AUTH", None)
        run_checked([sys.executable, str(ROOT / "tools/stage_ab_runtime.py"), str(checkout)], ROOT, environment, 120)
    if not (target / "SOURCE.json").is_file():
        raise RuntimeError("ADCP source staging produced no manifest")


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
