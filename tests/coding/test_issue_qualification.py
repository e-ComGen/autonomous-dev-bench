from dataclasses import replace
from types import SimpleNamespace
import base64
import pytest
from corpus.qualification.policy import IssuePolicy, policy_from_mapping
from corpus.qualification.files import safe_path, is_code, materialize, code_view, overlay
from corpus.qualification.workspace import RepositoryWorkspace
from corpus.qualification.junit import parse_junit, acceptance_sets, classify
from corpus.qualification.selection import Selection
from suites.coding.settings import load_campaign


def payload(value):
    return {"data": base64.b64encode(value.encode()).decode(), "executable": False}


def test_default_is_real_issue_not_synthetic_source():
    from pathlib import Path
    settings, policy = load_campaign(Path(__file__).resolve().parents[2] / "AB.toml")
    assert settings.task_source == "github_issue"
    assert policy.repositories == ()


@pytest.mark.parametrize("name", ["../../escape", "C:/secret", "x\\y", "/tmp/file", ".git/config", "a/CON.txt", "x."])
def test_untrusted_paths_are_rejected(name):
    with pytest.raises(ValueError):
        safe_path(name)


def test_complete_repository_and_hidden_test_separation(tmp_path):
    files = {"lib.py": payload("value = 1\n"), "tests/test_a.py": payload("hidden = False\n"), "image.bin": payload("asset")}
    view = code_view(files, 900000)
    assert view == {"lib.py": "value = 1\n"}
    workspace = RepositoryWorkspace(files, 1024)
    view["TASK.md"] = "Issue text"
    workspace.materialize(view, tmp_path)
    assert (tmp_path / "tests/test_a.py").read_bytes() == b"hidden = False\n"
    (tmp_path / "lib.py").write_bytes(b"value = 2\n")
    assert workspace.read_candidate(view, tmp_path)["lib.py"] == "value = 2\n"
    (tmp_path / "tests/test_a.py").write_bytes(b"assert True\n")
    with pytest.raises(ValueError, match="PROTECTED"):
        workspace.read_candidate(view, tmp_path)


def test_candidate_does_not_silently_normalize_crlf(tmp_path):
    files = {"lib.py": payload("value = 1\n")}
    view = code_view(files, 1024)
    workspace = RepositoryWorkspace(files, 1024)
    workspace.materialize(view, tmp_path)
    (tmp_path / "lib.py").write_bytes(b"value = 2\r\n")
    assert workspace.read_candidate(view, tmp_path)["lib.py"] == "value = 2\r\n"


def test_junit_rejects_empty_duplicates_and_entities():
    for value in (b'<testsuite/>', b'<!DOCTYPE a><testsuite/>',
                  b'<testsuite><testcase name="a"/><testcase name="a"/></testsuite>'):
        with pytest.raises(ValueError):
            parse_junit(value)


def test_qualification_requires_real_failure_and_preservation():
    public = {"regression": "PASS"}
    broken = {"bug": "FAIL", "existing": "PASS"}
    repaired = {"bug": "PASS", "existing": "PASS"}
    assert acceptance_sets(public, broken, repaired)["fail_to_pass"] == ["bug"]
    for invalid in ({"bug": "ERROR", "existing": "PASS"}, repaired, {"bug": "FAIL"}):
        with pytest.raises(ValueError):
            acceptance_sets(public, invalid, repaired)
    assert classify({"bug": "SKIP"}, {"bug": "PASS"}) == "FAIL"
    assert classify({}, {"bug": "PASS"}) == "EVALUATION_ERROR"


def test_project_quotas_are_not_filled_with_wrong_size():
    policy = replace(IssuePolicy(), large_projects=1)
    selection = Selection(policy, 1)
    assert not selection.wants("small/repo", "small")
    task = SimpleNamespace(project_id="large/repo")
    prepared = {"captured": {"classification": {"scale": "large"}}}
    assert selection.add(task, prepared)
    assert selection.complete


@pytest.mark.parametrize("value", [True, -1, 0, 1.5])
def test_acquisition_limits_reject_invalid_values(value):
    with pytest.raises(ValueError):
        replace(IssuePolicy(), max_candidates=value)


def test_configuration_typo_is_not_silently_ignored():
    with pytest.raises(ValueError):
        policy_from_mapping({"max_canddiates": 20})


def test_public_test_path_is_not_editable():
    assert not is_code("tests/test_x.py")
    assert not is_code("conftest.py")
    assert not is_code("setup.py")
    assert is_code("src/package/core.py")
