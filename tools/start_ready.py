"""No-input operator launch with paid A/B explicitly requested as the default.

Keys are never requested on stdin, passed in argv or logged. Diagnostic commands
remain non-billable. Existing runtime, budgets and development loop are reused.
"""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from tools.launcher_credentials import read_credentials, create_template, host_credentials


class ConfigurationRequired(ValueError):
    pass


def normalized_arguments(arguments):
    arguments = list(arguments)
    return ["ab", *arguments] if not arguments or arguments[0].startswith("-") else arguments


def configured_arguments(root, arguments, values):
    arguments = normalized_arguments(arguments)
    command = arguments[0]
    if command not in {"ab", "ab-preflight", "qualify", "discover"}:
        return arguments
    if "--help" in arguments or "-h" in arguments:
        return arguments
    replay = any(item == "--replay" or item.startswith("--replay=") for item in arguments)
    private_present = (Path(root) / ".bench/adcp/SOURCE.json").is_file()
    need_github = not replay or (command in {"ab", "ab-preflight"} and not private_present)
    missing = []
    if need_github and not values.get("GITHUB_TOKEN"):
        missing.append("GITHUB_TOKEN")
    if command == "ab":
        if not values.get("DEEPSEEK_API_KEY"):
            missing.append("DEEPSEEK_API_KEY")
        # The operator explicitly selected always-paid A/B for this entrypoint.
        # Preserve the existing execution contract instead of adding another gate.
        if "--allow-live-model" not in arguments:
            arguments.append("--allow-live-model")
    if missing:
        create_template(root)
        raise ConfigurationRequired("Set " + ", ".join(missing) + " in .env next to START.cmd. No model was called.")
    if command != "discover" and "--allow-local-execution" not in arguments:
        arguments.append("--allow-local-execution")
    return arguments


def save_startup(root, status, command, reason=None):
    state = Path(root) / ".bench"
    if state.is_symlink():
        raise ValueError(".bench must not be a symlink")
    state.mkdir(exist_ok=True)
    destination = state / "startup.json"
    if destination.is_symlink():
        raise ValueError("Startup report must not be a symlink")
    result = {"schema": "autobench.startup/v1", "status": status, "command": command,
              "launcher": "paid-ab-default-v2", "local_consent_prompt": False,
              "paid_ab_default": True}
    if reason:
        result["reason"] = reason
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")


def main(argv=None, root=ROOT):
    root = Path(root).resolve()
    arguments = normalized_arguments(sys.argv[1:] if argv is None else argv)
    command = arguments[0]
    interactive_commands = {"ab", "ab-preflight", "qualify", "discover"}
    help_only = "--help" in arguments or "-h" in arguments
    try:
        if command not in interactive_commands or help_only:
            return subprocess.call([sys.executable, "-I", str(root / "tools/launch.py"), *arguments], cwd=root)
        if sys.version_info < (3, 12):
            raise ValueError("Python 3.12 or newer is required")
        if "--offline" in arguments:
            raise ValueError("Real issue acquisition/A-B cannot run offline; test --offline is separate")
        values = read_credentials(root)
        arguments = configured_arguments(root, arguments, values)
        if command in {"ab", "ab-preflight", "qualify"}:
            from suites.coding.settings import load_launch_settings
            load_launch_settings(root, arguments)
            print("Config: settings-v2; A/B configuration validated before runtime preparation", flush=True)
        with host_credentials(values):
            if command in {"ab", "ab-preflight"}:
                from tools.prepare_ab import prepare_runtime
                if root != ROOT:
                    raise ValueError("Runtime acquisition is bound to the current release root")
                prepare_runtime()
            print("Launcher: paid-ab-default-v2; confirmation prompts disabled", flush=True)
            if command == "ab":
                print("A/B uses the paid provider; configured request/time budgets remain active.", flush=True)
            print("GitHub credential: " + ("present" if values["GITHUB_TOKEN"] else "not required for replay"), flush=True)
            save_startup(root, "DISPATCHING", command)
            return subprocess.call([sys.executable, "-I", str(root / "tools/launch.py"), *arguments],
                                   cwd=root, stdin=subprocess.DEVNULL, shell=False)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        message = str(error)[:1000]
        print("CONFIG_REQUIRED: " + message if isinstance(error, ConfigurationRequired) else "BLOCKED: " + message,
              file=sys.stderr)
        save_startup(root, "CONFIG_REQUIRED" if isinstance(error, ConfigurationRequired) else "BLOCKED", command, message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
