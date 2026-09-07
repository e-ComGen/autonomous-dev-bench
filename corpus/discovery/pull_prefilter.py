"""Cheap PR metadata rejection before Git acquisition; never grants qualification."""
from pathlib import PurePosixPath
from corpus.qualification.changes import documentation_only
from corpus.qualification.files import is_code, is_test, safe_path


def rejection_reason(pull):
    count = pull.get("changedFiles")
    if type(count) is not int or not 1 <= count <= 30:
        return "CHANGED_FILE_LIMIT"
    connection = pull.get("files")
    if not isinstance(connection, dict):
        return "PR_FILES_UNAVAILABLE"
    nodes = connection.get("nodes")
    page = connection.get("pageInfo")
    if (not isinstance(nodes, list) or not isinstance(page, dict)
            or page.get("hasNextPage") is not False
            or connection.get("totalCount") != count or len(nodes) != count):
        return "PR_FILES_INCOMPLETE"
    paths = []
    for item in nodes:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return "PR_FILES_UNAVAILABLE"
        path = item["path"]
        try:
            safe_path(path)
        except ValueError:
            return "UNSAFE_REPOSITORY_PATH"
        paths.append(path)
    if len(set(paths)) != count:
        return "PR_FILES_INCOMPLETE"
    code = {path for path in paths if is_code(path)}
    tests = {path for path in paths if is_test(path) and PurePosixPath(path).suffix == ".py"}
    if not code or not tests:
        return "NO_CODE_AND_TEST_CHANGE"
    for item in nodes:
        path, change = item["path"], item.get("changeType")
        if change not in {"ADDED", "MODIFIED", "DELETED", "RENAMED", "COPIED", "CHANGED", "UNCHANGED"}:
            return "PR_CHANGE_TYPE_UNAVAILABLE"
        if path in code and change != "MODIFIED":
            return "SOURCE_CREATION_DELETION_UNSUPPORTED"
        if path in tests and (change not in {"ADDED", "MODIFIED"} or PurePosixPath(path).name == "conftest.py"):
            return "TEST_HARNESS_CHANGE_UNSUPPORTED"
        if path not in code and path not in tests and not documentation_only(path):
            return "NON_PYTHON_OR_ENVIRONMENT_CHANGE"
    return None
