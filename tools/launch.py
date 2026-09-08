"""Private test venv and host-only credentials; no token loss across launcher processes."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.launcher_env import clean_environment
from tools.launcher_lock import launcher_lock
from tools.launcher_credentials import read_credentials


def invoke(argv, log, environment, timeout):
    with log.open("ab") as stream:
        result = subprocess.run(argv, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, shell=False)
    if result.returncode:
        raise RuntimeError(f"Bootstrap exited {result.returncode}; see {log}")


def verify_wheels(wheelhouse):
    manifest = wheelhouse / "SHA256SUMS.json"
    if not manifest.is_file():
        return False
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not entries or not isinstance(entries, dict):
        raise ValueError("Invalid wheel manifest")
    if {path.name for path in wheelhouse.glob("*.whl")} != set(entries):
        raise ValueError("Wheel manifest does not match wheelhouse")
    for name, expected in entries.items():
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("Unsafe wheel name")
        if hashlib.sha256((wheelhouse / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Wheel integrity failure: {name}")
    return True


def ensure_runtime(offline):
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required; no global packages were changed")
    state = ROOT / ".bench"
    if state.is_symlink():
        raise ValueError(".bench must not be a symlink")
    state.mkdir(exist_ok=True)
    requirement = ROOT / "tools/requirements-launcher.txt"
    identity = hashlib.sha256((str(ROOT) + sys.executable + sys.version).encode() + requirement.read_bytes()).hexdigest()
    runtime = state / ("runtime-" + identity[:12])
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker, log = runtime / ".ready", state / "bootstrap.log"
    environment = clean_environment(ROOT)
    if marker.is_file() and marker.read_text() == identity and python.is_file():
        probe = subprocess.run([str(python), "-I", "-c", "import pytest; assert pytest.__version__ == '8.4.2'"],
                               env=environment, capture_output=True, timeout=20)
        if probe.returncode == 0:
            return python
    print("Preparing isolated test environment; details: .bench/bootstrap.log", flush=True)
    if not python.is_file():
        invoke([sys.executable, "-I", "-m", "venv", str(runtime)], log, environment, 180)
    install = [str(python), "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check", "--only-binary=:all:"]
    wheelhouse = ROOT / "vendor/wheels"
    if verify_wheels(wheelhouse):
        install.extend(["--no-index", "--find-links", str(wheelhouse)])
    elif offline:
        raise RuntimeError("OFFLINE_WHEELS_MISSING: use the packaged release or one online bootstrap")
    else:
        install.extend(["--index-url", "https://pypi.org/simple"])
    invoke([*install, "-r", str(requirement)], log, environment, 300)
    marker.write_text(identity, encoding="ascii")
    return python


def command_name(arguments):
    # Help does not need application credentials, including `ab --help`.
    if "--help" in arguments or "-h" in arguments:
        return "help"
    return arguments[0] if arguments and not arguments[0].startswith("-") else "ab"


def host_environment(root, command):
    environment = clean_environment(root)
    execution = command in {"ab", "ab-preflight", "qualify"}
    if execution or command == "discover":
        credentials = read_credentials(root)
        for key in ("GITHUB_TOKEN", "GH_TOKEN"):
            if credentials[key]:
                environment[key] = credentials[key]
        if command == "ab" and credentials["DEEPSEEK_API_KEY"]:
            environment["DEEPSEEK_API_KEY"] = credentials["DEEPSEEK_API_KEY"]
    if execution:
        for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY"):
            if key in os.environ:
                environment[key] = os.environ[key]
        environment["DOCKER_CONFIG"] = os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker"))
    return environment


def main():
    arguments = sys.argv[1:] or ["ab"]
    try:
        with launcher_lock(ROOT / ".bench/launcher.lock"):
            command = command_name(arguments)
            environment = host_environment(ROOT, command)
            python = ensure_runtime("--offline" in arguments)
            return subprocess.call([str(python), "-B", str(ROOT / "tools/bench.py"), *arguments],
                                   cwd=ROOT, env=environment, shell=False)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
