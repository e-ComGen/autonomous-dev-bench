from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from benchmark_core.cas import FileSystemCAS
from corpus.discovery.diagnostics import summarize, top_reasons
from tools.export_discovery import export
from suites.coding.issue_preparation import save_discovery


def test_metadata_and_execution_failures_are_distinct_and_safe():
    details = {"api_requests": 6, "project_deficits": {"large": 0},
               "intake_rejections": [{"repository": "example/one", "pull": 1, "reason": "NO_CODE_AND_TEST_CHANGE"}],
               "qualification_rejections": [{"repository": "example/two", "pull": 2,
                    "reason": "PROJECT_BUILD_FAILED: secret-looking stderr must not enter compact report"}]}
    result = summarize(details, requested=1, qualified=0, stop_reason="SEARCH_POOL_EXHAUSTED")
    assert result["rejections"] == 2
    assert result["stages"]["metadata"]["reason_counts"] == {"NO_CODE_AND_TEST_CHANGE": 1}
    assert result["stages"]["execution"]["reason_counts"] == {"PROJECT_BUILD_FAILED": 1}
    assert "stderr" not in json.dumps(result)
    assert "NO_CODE_AND_TEST_CHANGE=1" in top_reasons(result)


def test_compact_report_keeps_causes_visible_without_cas_read(tmp_path):
    directory = tmp_path / "runs/one"
    directory.mkdir(parents=True)
    report = SimpleNamespace(directory=directory, cas=FileSystemCAS(tmp_path / "cas"))
    intake = SimpleNamespace(rejected=[{"reason": "NO_CODE_AND_TEST_CHANGE"}], counts={"pulls_inspected": 1}, searches=[])
    selection = SimpleNamespace(selected=[], deficits=lambda: {"small": 0, "medium": 0, "large": 0})
    save_discovery(report, SimpleNamespace(requests=2), intake, selection, [], 1, "SEARCH_POOL_EXHAUSTED")
    actual = json.loads((directory / "discovery.json").read_text())
    assert actual["reason_counts"] == {"NO_CODE_AND_TEST_CHANGE": 1}
    assert actual["requested_tasks"] == 1 and actual["qualified"] == 0
    assert actual["details_ref"].startswith("cas:")


def test_export_reads_previous_run_using_existing_cas(tmp_path):
    directory = tmp_path / ".bench/runs/prior"
    directory.mkdir(parents=True)
    cas = FileSystemCAS(tmp_path / ".bench/cas")
    ref = cas.put_text(json.dumps({"intake_rejections": [], "qualification_rejections": [
        {"repository": "example/package", "pull": 6, "reason": "NO_CODE_AND_TEST_CHANGE"}]}))
    (directory / "discovery.json").write_text(json.dumps({"details_ref": ref, "qualified": 0, "rejections": 1}))
    target = export(tmp_path)
    result = json.loads(target.read_text())
    assert target.parent == directory
    assert result["reason_counts"] == {"NO_CODE_AND_TEST_CHANGE": 1}
    assert result["stop_reason"] == "UNKNOWN_IN_OLD_REPORT"
    assert result["events"][0]["pull"] == 6


def test_no_old_run_is_not_reported_as_an_empty_success(tmp_path):
    with pytest.raises(ValueError, match="NO_SAVED_DISCOVERY_REPORT"):
        export(tmp_path)
