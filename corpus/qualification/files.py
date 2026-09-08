"""Portable full-repository payloads and an explicit editable Python projection."""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import re
import stat


IGNORED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def safe_path(value):
    path = PurePosixPath(value)
    if (not value or str(path) != value or path.is_absolute() or ".." in path.parts
            or any(part in {".git", ".hg", ".svn"} for part in path.parts)
            or any(char in value for char in '\\:\x00<>"|?*') or any(ord(char) < 32 for char in value)
            or any(part.endswith((" ", ".")) for part in path.parts)
            or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", part) for part in path.parts)):
        raise ValueError("UNSAFE_REPOSITORY_PATH")
    return Path(*path.parts)


def is_test(path):
    value = PurePosixPath(path)
    return bool({"tests", "test", "testing"} & set(value.parts)) or value.name.startswith("test_") or value.name.endswith("_test.py")


def is_pytest_module(path):
    """A protected test asset is not necessarily an executable pytest target."""
    value = PurePosixPath(path)
    return value.suffix == ".py" and (value.name.startswith("test_") or value.name.endswith("_test.py"))


def is_code(path):
    value = PurePosixPath(path)
    return (value.suffix == ".py" and not is_test(path) and value.name not in {"setup.py", "conftest.py"}
            and not {"docs", "doc", "examples", ".github", "benchmarks"} & set(value.parts))


def capture_files(directory, policy):
    directory = Path(directory)
    files, total = {}, 0
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if ".git" in Path(relative).parts:
            continue
        safe_path(relative)
        if path.is_symlink():
            raise ValueError("LINKED_SOURCE_UNSUPPORTED")
        if path.is_file():
            size = path.stat().st_size
            total += size
            if size > policy.max_file_bytes or total > policy.max_repository_bytes:
                raise ValueError("SOURCE_SIZE_LIMIT")
            payload = path.read_bytes()
            files[relative] = {"data": base64.b64encode(payload).decode("ascii"),
                               "executable": bool(path.stat().st_mode & stat.S_IXUSR)}
    return files


def materialize(directory, files):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for relative, record in files.items():
        path = directory / safe_path(relative)
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != directory.parent):
            raise ValueError("LINKED_MATERIALIZATION_TARGET")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(record["data"], validate=True))
        path.chmod(0o755 if record.get("executable") else 0o644)


def text(record):
    return base64.b64decode(record["data"], validate=True).decode("utf-8")


def code_view(files, limit):
    result = {path: text(record) for path, record in files.items() if is_code(path)}
    if not result or sum(len(value.encode("utf-8")) for value in result.values()) > limit:
        raise ValueError("ADCP_SOURCE_VIEW_UNSUPPORTED")
    if len({path.casefold() for path in files}) != len(files):
        raise ValueError("CASE_COLLIDING_SOURCE")
    return result


def overlay(files, projection):
    result = dict(files)
    for path, content in projection.items():
        safe_path(path)
        if path not in files and path not in {"TASK.md", "public_tests.py"}:
            raise ValueError("NEW_SOURCE_PATH_UNSUPPORTED")
        previous = files.get(path, {})
        result[path] = {"data": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                        "executable": previous.get("executable", False)}
    return result


def scale(files):
    lines = sum(text(record).count("\n") + 1 for path, record in files.items() if is_code(path))
    return {"python_lines": lines, "scale": "small" if lines < 5000 else "medium" if lines < 20000 else "large"}
