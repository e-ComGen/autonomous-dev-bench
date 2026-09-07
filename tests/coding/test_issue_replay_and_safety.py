from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
import json
import pytest
from corpus.qualification.changes import partition, documentation_only
from corpus.qualification.selection import Selection
from corpus.qualification.policy import IssuePolicy
from suites.coding.fingerprint import implementation_fingerprint
from cli.oneclick.report import Report


def test_dependency_change_is_not_treated_as_harmless_documentation():
    before = {"lib.py": "old", "tests/test_lib.py": "old", "requirements.txt": "old"}
    after = {key: "new" for key in before}
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        partition(before, after)
    assert not documentation_only("requirements.txt")
    assert not documentation_only("docs/requirements.txt")
    assert documentation_only("changelog.d/123.bugfix")
    assert documentation_only("README.md")


def test_replay_fingerprint_changes_with_execution_code(tmp_path):
    source = tmp_path / "suites/coding/a.py"
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n")
    first = implementation_fingerprint(tmp_path)
    source.write_text("x = 2\n")
    assert first != implementation_fingerprint(tmp_path)


def test_large_campaign_details_do_not_pollute_operator_summary(tmp_path):
    report = Report(tmp_path, "ab")
    rows = [{"arm": "stock", "details": "x" * 3000} for _ in range(100)]
    summary = report.save({"status": "RUNNING", "rows": rows, "live_model_called": True})
    value = json.loads(summary.read_text())
    assert "rows" not in value and value["rows_count"] == 100
    assert json.loads(report.cas.get_text(value["rows_ref"])) == rows
    assert summary.stat().st_size < 2048


def test_quota_counts_distinct_projects_not_multiple_tasks():
    policy = replace(IssuePolicy(), large_projects=2, tasks_per_project=3)
    selection = Selection(policy, 2)
    value = {"captured": {"classification": {"scale": "large"}}}
    assert selection.add(SimpleNamespace(project_id="a/a"), value)
    assert not selection.add(SimpleNamespace(project_id="a/a"), value)
    assert not selection.complete
    assert selection.add(SimpleNamespace(project_id="b/b"), value)
    assert selection.complete
