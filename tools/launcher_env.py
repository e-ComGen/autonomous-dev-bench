"""An allowlist for benchmark subprocesses, not an OS sandbox."""
from pathlib import Path
import os
import tempfile

_SYSTEM = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
           "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL"}


def clean_environment(root: Path, *, github: bool = False) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in _SYSTEM}
    # Preserve the operator's original temp parent before redirecting ordinary
    # subprocess TMP. Nested launcher calls must not add the checkout prefix.
    # Tests allocate and delete only a new private child of this directory.
    test_parent = Path(os.environ.get("AUTOBENCH_TEST_TMPDIR") or tempfile.gettempdir()).resolve()
    if not test_parent.is_dir():
        raise ValueError("Test scratch parent does not exist")
    environment["AUTOBENCH_TEST_TMPDIR"] = str(test_parent)
    state = root / ".bench"
    if state.is_symlink():
        raise ValueError(".bench must not be a symlink")
    for name in ("home", "tmp"):
        directory = state / name
        if directory.is_symlink():
            raise ValueError("Managed state directories must not be symlinks")
        directory.mkdir(parents=True, exist_ok=True)
    environment.update({
        "HOME": str(state / "home"), "USERPROFILE": str(state / "home"),
        "TMP": str(state / "tmp"), "TEMP": str(state / "tmp"),
        "TMPDIR": str(state / "tmp"), "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": os.pathsep.join((str(root), str(root / "packages/benchmark_core"))),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.longpaths",
        "GIT_CONFIG_VALUE_0": "true", "GIT_CONFIG_KEY_1": "core.autocrlf",
        "GIT_CONFIG_VALUE_1": "false", "GIT_TERMINAL_PROMPT": "0",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    })
    if github and os.environ.get("GITHUB_TOKEN"):
        environment["GITHUB_TOKEN"] = os.environ["GITHUB_TOKEN"]
    return environment
