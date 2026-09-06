import json
from pathlib import Path
import re
import pytest

from benchmark_core.assets import asset_path
from benchmark_core.manifest import load_json, load_project, load_scenario, load_suite, load_task


ROOT = Path(__file__).parents[2]


def test_source_asset_locator_is_confined() -> None:
    assert asset_path("tasks/httpx.add_transport_provider.v1.json").is_file()
    with pytest.raises(ValueError, match="confined"):
        asset_path("../private-labels.json")
    with pytest.raises(FileNotFoundError):
        asset_path("tasks/not-present.json")


def test_public_corpus_is_fully_content_pinned() -> None:
    manifests = sorted((ROOT / "corpus" / "projects").glob("*.json"))
    assert {path.stem for path in manifests} >= {
        "httpx.pinned_001", "requests.pinned_001", "pluggy.pinned_001"
    }
    commits: set[str] = set()
    for path in manifests:
        value = json.loads(path.read_text(encoding="utf-8"))
        commit = value["source"]["commit_sha"]
        digest = value["source"]["source_tree_digest"]
        assert re.fullmatch(r"[0-9a-f]{40}", commit)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        assert "latest" not in path.read_text(encoding="utf-8").casefold()
        commits.add(commit)
    assert len(commits) == len(manifests)


def test_public_manifests_load_into_immutable_schemas() -> None:
    for path in (ROOT / "corpus" / "projects").glob("*.json"):
        assert load_project(path).identity.content_digest is not None
    pairs = (
        (ROOT / "tasks" / "selftest.add_provider.v1.json", ROOT / "scenarios" / "synthetic" / "shared_provider_task.v1.json"),
        (ROOT / "tasks" / "httpx.add_transport_provider.v1.json", ROOT / "scenarios" / "real_world" / "httpx.add_transport_provider.shared.v1.json"),
    )
    for task_path, scenario_path in pairs:
        task = load_task(task_path)
        scenario = load_scenario(scenario_path)
        assert scenario.task_id == task.task_id
        assert scenario.mutations[0].output_checkpoint == "candidate_bad_dispatch"
        assert scenario.execution.environment["network"] == "none"


def test_json_loaders_reject_duplicate_keys_and_coercive_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"value": 1, "value": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_json(duplicate)
    scenario_path = ROOT / "scenarios" / "synthetic" / "shared_provider_task.v1.json"
    value = json.loads(scenario_path.read_text(encoding="utf-8"))
    value["execution"]["timeout_seconds"] = True
    malformed = tmp_path / "scenario.json"
    malformed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="integer"):
        load_scenario(malformed)


def test_suite_manifests_match_runtime_plans_exactly() -> None:
    from suites.auto_refactoring import plan as refactoring_plan
    from suites.auto_zoning import plan as zoning_plan
    assert load_suite(ROOT / "suites" / "auto_refactoring" / "suite.v4.json") == refactoring_plan()
    assert load_suite(ROOT / "suites" / "auto_zoning" / "suite.v3.json") == zoning_plan()


def test_shared_scenario_contains_no_suite_answers() -> None:
    value = json.loads((ROOT / "scenarios" / "synthetic" / "shared_provider_task.v1.json").read_text(encoding="utf-8"))
    serialized = json.dumps(value).casefold()
    for forbidden in ("expected_answer", "ground_truth", "oracle_labels", "responsibility_labels"):
        assert forbidden not in serialized
    assert set(value["suites"]) == {"auto_refactoring", "auto_zoning"}
