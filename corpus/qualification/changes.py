"""Conservative PR separation: fixes and protected tests must not change the environment."""
from pathlib import PurePosixPath
from .files import is_code, is_test, safe_path


def documentation_only(path):
    value = PurePosixPath(path)
    parts = {part.casefold() for part in value.parts}
    name = value.name.casefold()
    if any(word in name for word in ("requirement", "constraint", "lock")):
        return False
    if value.suffix.casefold() in {".md", ".rst"}:
        return True
    return bool(parts & {"news", "changelog", "changelogs", "changes", "docs", "doc", "changelog.d"})


def partition(before, after):
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    code = sorted(path for path in changed if is_code(path))
    tests = sorted(path for path in changed if is_test(path) and PurePosixPath(path).suffix == ".py")
    if not code or not tests:
        raise ValueError("NO_CODE_AND_TEST_CHANGE")
    if any(path not in before or path not in after for path in code):
        raise ValueError("SOURCE_CREATION_DELETION_UNSUPPORTED")
    if any(path not in after or PurePosixPath(path).name == "conftest.py" for path in tests):
        raise ValueError("TEST_HARNESS_CHANGE_UNSUPPORTED")
    harmless = {path for path in changed if documentation_only(path)}
    if changed - set(code) - set(tests) - harmless:
        raise ValueError("NON_PYTHON_OR_ENVIRONMENT_CHANGE")
    for path in changed:
        safe_path(path)
    return code, tests
