from copy import deepcopy
import pytest
from corpus.discovery.pull_prefilter import rejection_reason
from corpus.qualification.changes import partition


def pull(*paths):
    nodes = [{"path": name, "changeType": change} for name, change in paths]
    return {"changedFiles": len(nodes), "files": {"totalCount": len(nodes),
            "pageInfo": {"hasNextPage": False}, "nodes": nodes}}


def eligible():
    return pull(("src/library/core.py", "MODIFIED"), ("tests/test_core.py", "ADDED"))


@pytest.mark.parametrize("paths,reason", [
    ((("library/drivers.py", "MODIFIED"),), "NO_CODE_AND_TEST_CHANGE"),
    ((("tests/test_core.py", "ADDED"),), "NO_CODE_AND_TEST_CHANGE"),
    ((("core.py", "ADDED"), ("tests/test_core.py", "ADDED")), "SOURCE_CREATION_DELETION_UNSUPPORTED"),
    ((("core.py", "MODIFIED"), ("tests/conftest.py", "MODIFIED")), "TEST_HARNESS_CHANGE_UNSUPPORTED"),
    ((("core.py", "MODIFIED"), ("tests/test_core.py", "DELETED")), "TEST_HARNESS_CHANGE_UNSUPPORTED"),
    ((("core.py", "MODIFIED"), ("tests/test_core.py", "ADDED"), ("pyproject.toml", "MODIFIED")), "NON_PYTHON_OR_ENVIRONMENT_CHANGE"),
    ((("../core.py", "MODIFIED"), ("test_core.py", "ADDED")), "UNSAFE_REPOSITORY_PATH"),
])
def test_unsupported_shape_rejected_before_clone(paths, reason):
    assert rejection_reason(pull(*paths)) == reason


def test_paths_are_only_prefilter_not_qualification():
    value = eligible()
    before = deepcopy(value)
    assert rejection_reason(value) is None
    assert value == before
    # The original full-tree check is unchanged and still rejects no-test changes.
    with pytest.raises(ValueError, match="NO_CODE_AND_TEST_CHANGE"):
        partition({"core.py": "before"}, {"core.py": "after"})


def test_documentation_does_not_hide_environment_changes():
    assert rejection_reason(pull(("core.py", "MODIFIED"), ("test_core.py", "ADDED"),
                                 ("README.md", "MODIFIED"))) is None
    assert rejection_reason(pull(("core.py", "MODIFIED"), ("test_core.py", "ADDED"),
                                 ("docs/requirements.txt", "MODIFIED"))) == "NON_PYTHON_OR_ENVIRONMENT_CHANGE"


@pytest.mark.parametrize("mutation", ["missing", "truncated", "count", "duplicate", "null_node", "unknown_change"])
def test_incomplete_metadata_cannot_be_treated_as_complete(mutation):
    value = eligible()
    if mutation == "missing":
        value.pop("files")
    elif mutation == "truncated":
        value["files"]["pageInfo"]["hasNextPage"] = True
    elif mutation == "count":
        value["files"]["totalCount"] = 8
    elif mutation == "duplicate":
        value["files"]["nodes"][1] = value["files"]["nodes"][0]
    elif mutation == "null_node":
        value["files"]["nodes"][1] = None
    else:
        value["files"]["nodes"][0]["changeType"] = "UNKNOWN"
    assert rejection_reason(value) is not None
