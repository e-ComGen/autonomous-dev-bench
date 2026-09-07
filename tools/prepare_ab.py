"""Prepare the existing private ADCP runtime, then use the existing A/B entrypoint."""
from __future__ import annotations

import base64
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ADCP_REPOSITORY = "https://github.com/e-ComGen/autonomous-dev-control-plane.git"
ADCP_COMMIT = "b9c933bd7727b86149da891c323a27cde5afc956"


def clean_acquisition_environment() -> dict[str, str]:
    """Do not expose model or unrelated service credentials to Git."""
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull, "PYTHONUTF8": "1"})
    return result


def run_checked(argv: list[str], directory: Path, environment: dict[str, str], seconds: int) -> None:
    completed = subprocess.run(argv, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=seconds,
                               text=True, encoding="utf-8", errors="replace", shell=False)
    if completed.returncode:
        # Authentication headers are never part of argv or diagnostics.
        raise RuntimeError(f"Runtime preparation failed: {Path(argv[0]).name}, exit {completed.returncode}")


def read_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise RuntimeError("ADCP_RUNTIME_MISSING: provide GITHUB_TOKEN with read access to the private ADCP repository")
    print("The benchmark needs your private ADCP runtime. A read-only GitHub token is used only to download its pinned source.")
    token = getpass.getpass("GitHub token (hidden; not saved): ").strip()
    if not token:
        raise RuntimeError("ADCP_RUNTIME_MISSING: no GitHub credential supplied")
    return token


def prepare_runtime() -> None:
    target = ROOT / ".bench" / "adcp"
    if target.is_symlink() or (ROOT / ".bench").is_symlink():
        raise RuntimeError("Runtime storage must not be a symlink")
    if (target / "SOURCE.json").is_file():
        # The execution entrypoint validates every pinned source file before import.
        return
    if not shutil.which("git"):
        raise RuntimeError("Install Git before preparing the ADCP runtime")
    token = read_token()
    environment = clean_acquisition_environment()
    environment["AUTOBENCH_GIT_AUTH"] = "AUTHORIZATION: basic " + base64.b64encode(
        ("x-access-token:" + token).encode("utf-8")).decode("ascii")
    token = ""
    with tempfile.TemporaryDirectory(prefix="adb-source-") as temporary:
        checkout = Path(temporary)
        run_checked(["git", "-c", "core.longpaths=true", "init", "--quiet"], checkout, environment, 30)
        command = ["git", "--config-env=http.https://github.com/.extraheader=AUTOBENCH_GIT_AUTH",
                   "-c", "credential.helper=", "-c", "http.followRedirects=false",
                   "-c", "core.longpaths=true", "fetch", "--quiet", "--depth=1", "--no-tags",
                   ADCP_REPOSITORY, ADCP_COMMIT]
        try:
            run_checked(command, checkout, environment, 300)
        finally:
            environment.pop("AUTOBENCH_GIT_AUTH", None)
        run_checked([sys.executable, str(ROOT / "tools/stage_ab_runtime.py"), str(checkout)],
                    ROOT, environment, 120)
    if not (target / "SOURCE.json").is_file():
        raise RuntimeError("ADCP_RUNTIME_MISSING: source staging produced no manifest")


def main() -> int:
    arguments = sys.argv[1:]
    command = arguments[0] if arguments and not arguments[0].startswith("-") else "ab"
    if command in {"ab", "ab-preflight"}:
        if sys.version_info < (3, 12):
            print("BLOCKED: the real ADCP runtime requires Python 3.12 or newer.", file=sys.stderr)
            return 2
        if "--offline" in arguments:
            print("BLOCKED: a live model comparison cannot be performed offline; use test --offline for self-checks.", file=sys.stderr)
            return 2
        try:
            prepare_runtime()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"BLOCKED: {error}", file=sys.stderr)
            return 2
    return subprocess.call([sys.executable, "-I", str(ROOT / "tools/launch.py"), *arguments], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
