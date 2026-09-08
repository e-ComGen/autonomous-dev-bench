"""Private process environment and portable paths. This is NOT an OS sandbox."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys

SYSTEM_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL",
               "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}


def python_path(environment):
    return Path(environment) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def private_environment(directory, project_python=None, workspace=None, local_projects=()):
    directory = Path(directory).resolve()
    values = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
    for name in ("home", "cache", "tmp", "roaming", "local"):
        path = directory / name
        if path.is_symlink():
            raise ValueError("Native scratch must not contain links")
        path.mkdir(parents=True, exist_ok=True)
    values.update(HOME=str(directory / "home"), USERPROFILE=str(directory / "home"),
        APPDATA=str(directory / "roaming"), LOCALAPPDATA=str(directory / "local"),
        XDG_CACHE_HOME=str(directory / "cache"), TMP=str(directory / "tmp"),
        TEMP=str(directory / "tmp"), TMPDIR=str(directory / "tmp"), PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONHASHSEED="0",
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
        PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CONFIG_FILE=os.devnull,
        LOGNAME="autobenchmark", USER="autobenchmark", LNAME="autobenchmark", USERNAME="autobenchmark",
        GIT_AUTHOR_NAME="autobenchmark", GIT_AUTHOR_EMAIL="autobenchmark@invalid",
        GIT_COMMITTER_NAME="autobenchmark", GIT_COMMITTER_EMAIL="autobenchmark@invalid")
    prefixes = []
    if project_python:
        prefixes.append(str(Path(project_python).parent))
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            install = Path(git).resolve().parent.parent
            prefixes += [str(path) for path in (install / "bin", install / "usr/bin") if path.is_dir()]
    values["PATH"] = os.pathsep.join(prefixes + [values.get("PATH", "")])
    if workspace:
        source = Path(workspace).resolve()
        roots = [str(source / "src"), str(source)]
        if not isinstance(local_projects, (list, tuple)):
            raise ValueError("Invalid local source roots")
        for name in local_projects:
            if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Invalid local source root")
            path = (source / name).resolve()
            if not path.is_relative_to(source) or path == source:
                raise ValueError("Local source root escapes workspace")
            roots.extend((str(path / "src"), str(path)))
        values["PYTHONPATH"] = os.pathsep.join(roots)
    return values


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            result.update(chunk)
    return result.hexdigest()


def interpreter_identity():
    import platform
    return {"executable": str(Path(sys.executable).resolve()), "version": sys.version,
            "platform": sys.platform, "machine": platform.machine()}


def wheel_manifest(wheelhouse):
    return {path.name: digest_file(path) for path in sorted(Path(wheelhouse).glob("*.whl"))}


def verify_wheels(wheelhouse, expected):
    if not isinstance(expected, dict) or not expected or wheel_manifest(wheelhouse) != expected:
        raise ValueError("NATIVE_WHEEL_INTEGRITY_FAILURE")
    if any(Path(name).name != name for name in expected):
        raise ValueError("Unsafe wheel manifest")
