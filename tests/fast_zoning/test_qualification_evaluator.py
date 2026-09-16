"""Protocol parity against frozen source evaluator functions, without models."""
from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from benchmark_core.fast_zoning.qualification_evaluator import (
    CATEGORY_MAPPING, evaluate_binding, translate_evaluators,
)

MODULES = Path(__file__).parent / "fixtures" / "qualification_source"


def artifact(path: Path, value: bytes) -> str:
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def plan_for(row: dict) -> dict:
    return {"schema_version": 1, "benchmark_id": "offline-parity", "phase": "PREDECLARED",
            **{requirement: category == row["category"]
               for category, (_, requirement) in CATEGORY_MAPPING.items()}, "evaluators": [row]}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.mark.parametrize("status,body", [
    ("PASS", "assert True"), ("FAIL", "assert False"),
    ("ERROR", "raise RuntimeError('broken import')"),
])
def test_oracle_preserves_assertion_failure_vs_infrastructure_error(tmp_path, source_repo, status, body):
    oracle = tmp_path / "oracle.py"
    digest = artifact(oracle, ("def test_top_level_block_spoiler():\n    " + body + "\n").encode())
    plan = plan_for({"id": "oracle", "category": "NARROW_ORACLE", "runner": "frozen_oracle",
                     "oracle_path": oracle.name, "oracle_sha256": digest})
    rows = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "bound")
    result = evaluate_binding(Path(rows[0]["artifacts"][1]["path"]), Path(source_repo["repo"]), "oracle")
    assert result["status"] == status
    assert Path(result["detail"]["log"]).is_file()


@pytest.mark.parametrize("status,content", [
    ("PASS", "def test_value():\n    assert True\n"),
    ("FAIL", "def test_value():\n    assert False\n"),
    ("ERROR", "raise RuntimeError('collection failure')\n"),
    ("ERROR", "import pytest\ndef test_value():\n    pytest.skip('not measured')\n"),
])
def test_existing_suite_retains_source_failure_collection_and_skip_semantics(tmp_path, source_repo, status, content):
    repo = Path(source_repo["repo"])
    (repo / "tests").mkdir()
    (repo / "tests" / "test_value.py").write_text(content, encoding="utf-8")
    git(repo, "add", "tests")
    git(repo, "commit", "-m", "frozen suite fixture")
    plan = plan_for({"id": "suite", "category": "EXISTING_SUITE", "runner": "pytest",
                     "args": ["tests/test_value.py"]})
    rows = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "bound")
    result = evaluate_binding(Path(rows[0]["artifacts"][1]["path"]), repo, "suite")
    assert result["status"] == status
    assert result["command"][-1] == "tests/test_value.py"
    assert (Path(result["source_evidence_directory"]) / "0" / "suite.log").is_file()


@pytest.mark.parametrize("status,observed", [
    ("PASS", [{"id": "one", "outcome": 1}]),
    ("FAIL", [{"id": "one", "outcome": 2}]),
    ("ERROR", [{"id": "wrong-case", "outcome": 1}]),
])
def test_differential_preserves_behavior_difference_vs_incomplete_coverage(tmp_path, source_repo, status, observed):
    row = {"id": "diff", "category": "DIFFERENTIAL_CHECK", "runner": "differential"}
    data = {"cases": gzip.compress(b'[{"id":"one"}]', mtime=0),
            "reference": gzip.compress(b'{"results":[{"id":"one","outcome":1}]}', mtime=0),
            "probe": ("import json,sys\nfrom pathlib import Path\n"
                      f"Path(sys.argv[3]).write_text(json.dumps({{'results': {observed!r}}}))\n").encode()}
    for stem, payload in data.items():
        path = tmp_path / (stem + (".py" if stem == "probe" else ".json.gz"))
        row[stem + "_path"] = path.name
        row[stem + "_sha256"] = artifact(path, payload)
    rows = translate_evaluators(plan_for(row), tmp_path / "plan.json", MODULES, tmp_path / "bound")
    result = evaluate_binding(Path(rows[0]["artifacts"][1]["path"]), Path(source_repo["repo"]), "diff")
    assert result["status"] == status
    if status != "ERROR":
        assert result["cases_total"] == 1
        assert result["cases_differ"] == (status == "FAIL")


def test_binding_is_portable_and_pins_transitive_source_before_execution(tmp_path, source_repo):
    plan = plan_for({"id": "suite", "category": "EXISTING_SUITE", "runner": "pytest", "args": ["tests"]})
    left = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "left")
    right = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "right")
    assert (tmp_path / "left" / "binding.json").read_bytes() == (tmp_path / "right" / "binding.json").read_bytes()
    assert [a["sha256"] for a in left[0]["artifacts"]] == [a["sha256"] for a in right[0]["artifacts"]]
    (tmp_path / "left" / "oracle_runner.py").write_text("raise AssertionError('must not execute')")
    with pytest.raises(ValueError, match="dependency changed"):
        evaluate_binding(tmp_path / "left" / "binding.json", Path(source_repo["repo"]), "suite")


def test_translation_preserves_all_required_and_optional_categories_without_mutating_source(tmp_path):
    oracle = tmp_path / "oracle.py"
    digest = artifact(oracle, b"def test_top_level_block_spoiler(): pass\n")
    plan = {"evaluators": []}
    for index, (category, (_, requirement)) in enumerate(CATEGORY_MAPPING.items()):
        plan[requirement] = index % 2 == 0
        plan["evaluators"].append({"id": category, "category": category, "runner": "frozen_oracle",
                                   "oracle_path": oracle.name, "oracle_sha256": digest})
    original = deepcopy(plan)
    rows = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "bound")
    assert plan == original
    assert len(rows) == len(plan["evaluators"])
    assert {r["id"] for r in rows if r["required"]} == {
        r["id"] for r in plan["evaluators"] if plan[CATEGORY_MAPPING[r["category"]][1]]}


def test_hash_mismatch_prevents_source_artifact_execution(tmp_path):
    oracle = tmp_path / "oracle.py"
    artifact(oracle, b"raise AssertionError('must not execute')")
    plan = plan_for({"id": "oracle", "category": "NARROW_ORACLE", "runner": "frozen_oracle",
                     "oracle_path": oracle.name, "oracle_sha256": "0" * 64})
    with pytest.raises(ValueError, match="hash mismatch"):
        translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "bound")


def test_translated_command_satisfies_existing_campaign_json_protocol(tmp_path, source_repo):
    from benchmark_core.fast_zoning.evaluation import run_evaluators
    oracle = tmp_path / "oracle.py"
    digest = artifact(oracle, b"def test_top_level_block_spoiler():\n    assert True\n")
    plan = plan_for({"id": "oracle", "category": "NARROW_ORACLE", "runner": "frozen_oracle",
                     "oracle_path": oracle.name, "oracle_sha256": digest})
    rows = translate_evaluators(plan, tmp_path / "plan.json", MODULES, tmp_path / "bound")
    evidence = run_evaluators({"evaluation_plan_digest": "frozen-test-plan", "_evaluators": rows},
                              Path(source_repo["repo"]), tmp_path / "evidence")
    assert evidence["results"]["oracle"]["status"] == "PASS"
    assert evidence["results"]["oracle"]["exit_code"] == 0
