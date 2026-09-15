import hashlib
import json
from pathlib import Path

import pytest

from benchmark_core.fast_zoning.manifest import InvalidManifest, plan_digest, run_order, validate_manifest


def change(path, mutate):
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("field", ["clean_head", "clean_tree", "buggy_head", "buggy_tree"])
def test_invalid_commit_or_tree_cannot_validate(task_manifest, field):
    change(task_manifest, lambda data: data.update({field: "f" * 40}))
    with pytest.raises(InvalidManifest):
        validate_manifest(task_manifest)


def test_dirty_source_rejected(task_manifest):
    data = json.loads(task_manifest.read_text())
    (Path(data["repo"]) / "untracked.txt").write_text("dirty")
    with pytest.raises(InvalidManifest, match="dirty"):
        validate_manifest(task_manifest)


@pytest.mark.parametrize("field,value", [("packet_hash", "0" * 64), ("packet_bytes", 1),
                                         ("task_text", "Different task"), ("task_hash", "0" * 64)])
def test_packet_or_task_mismatch_rejected(task_manifest, field, value):
    change(task_manifest, lambda data: data["contexts"]["B"].update({field: value}))
    with pytest.raises(InvalidManifest):
        validate_manifest(task_manifest)


def test_evaluator_digest_mismatch_rejected(task_manifest):
    change(task_manifest, lambda data: data.update(evaluation_plan_digest="0" * 64))
    with pytest.raises(InvalidManifest, match="digest"):
        validate_manifest(task_manifest)


def test_mutated_evaluator_artifact_rejected(task_manifest):
    data = json.loads(task_manifest.read_text())
    artifact = Path(data["evaluation_plan"]["evaluators"][0]["artifacts"][0]["path"])
    artifact.write_text("different evaluator")
    with pytest.raises(InvalidManifest, match="hash"):
        validate_manifest(task_manifest)


def test_hidden_gold_snippet_blocked_even_with_valid_packet_hash(task_manifest):
    def mutate(data):
        data["evaluator_only"] = {"forbidden_snippets": ["SECRET GOLD FIX"]}
        packet = Path(data["contexts"]["A"]["packet_path"])
        packet.write_text(data["task_text"] + "\nSECRET GOLD FIX")
        data["contexts"]["A"].update(packet_hash=hashlib.sha256(packet.read_bytes()).hexdigest(), packet_bytes=packet.stat().st_size)
    change(task_manifest, mutate)
    with pytest.raises(InvalidManifest, match="hidden/gold"):
        validate_manifest(task_manifest)


def test_post_hoc_plan_cannot_authorize_execution(task_manifest):
    def mutate(data):
        data["evaluation_plan"]["phase"] = "POST_HOC_ANALYSIS"
        data["evaluation_plan_digest"] = plan_digest(data["evaluation_plan"])
    change(task_manifest, mutate)
    with pytest.raises(InvalidManifest, match="predeclared"):
        validate_manifest(task_manifest)


def test_same_seed_freezes_order_without_observing_results(task_manifest):
    result = validate_manifest(task_manifest)
    assert result["_run_order"] == run_order("offline-fixture-seed")
    assert result["_run_order"] == validate_manifest(task_manifest)["_run_order"]
    assert set(result["_run_order"]) == {"A", "B"}


def test_model_or_tool_override_cannot_change_one_arm(task_manifest):
    change(task_manifest, lambda data: data["contexts"]["B"].update(tools="read"))
    with pytest.raises(InvalidManifest, match="override"):
        validate_manifest(task_manifest)
