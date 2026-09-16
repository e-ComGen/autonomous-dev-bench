"""Packet provenance is importable independently from its quality qualification."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from benchmark_core.fast_zoning.manifest import InvalidManifest, validate_manifest
from test_qualification_import import qualification, import_fixture


@pytest.fixture
def packet_source(qualification):
    imported = import_fixture(qualification)
    root = qualification["out"].parent / "packet-source"
    root.mkdir()
    manifest = {
        "TASK_ID": "TEST-01", "TASK_TEXT": qualification["plan"]["task_text"],
        "TASK_SHA256": imported["task_hash"], "TARGET_HINTS": [],
        "BENCHMARK_HEAD": qualification["plan"]["benchmark_head"],
        "BENCHMARK_TREE": qualification["plan"]["benchmark_tree"],
        "CLEAN_HEAD": qualification["plan"]["reference_head"],
        "CLEAN_TREE": qualification["plan"]["reference_tree"],
        "EVALUATION_PLAN_DIGEST": imported["source_evaluation_plan_digest"],
        "MODEL_EXECUTED": False, "PACKETS_READY": "YES",
        "ARM_A_POLICY": "ORDINARY_CONTEXT_PLANNER_NO_ZONING_SEEDS",
        "ARM_B_POLICY": "REAL_AUTO_ZONING_TASK_ONLY_SELECTION_THEN_ZONE_AWARE_PLANNER",
        "B_ZONE_ID": "fixture-zone", "B_ZONE_ARTIFACT_PATHS": ["logic.py"],
        "B_SNAPSHOT_ID": "fixture-snapshot", "B_ANALYSIS_DIGEST": "sha256:" + "a" * 64,
        "B_ZONE_SELECTION": {"dependency": "UNATTRIBUTED"},
        "SHARED_PLANNER_STACK_SHA256": {"planner.py": "b" * 64},
    }
    for arm in ("A", "B"):
        blob = Path(qualification["contexts"][arm]["packet_path"]).read_bytes()
        path = root / f"{arm}.packet"
        path.write_bytes(blob)
        manifest.update({f"{arm}_PACKET_PATH": path.name,
                         f"{arm}_PACKET_SHA256": hashlib.sha256(blob).hexdigest(),
                         f"{arm}_PACKET_BYTES": len(blob), f"{arm}_SOURCE_ITEM_COUNT": 0,
                         f"{arm}_SOURCE_BYTES": 0, f"{arm}_BODY_SUBJECTS": [],
                         f"{arm}_PLANNING_TIME": 0.25})
    path = root / "packet-manifest.json"
    path.write_text(json.dumps(manifest, indent=3) + "\n", encoding="utf-8")
    return {"fixture": qualification, "original": imported, "root": root, "path": path,
            "manifest": manifest, "output": root.parent / "packets-v1"}


def bind(source, **kwargs):
    from benchmark_core.fast_zoning.packet_import import import_packet_manifest
    return import_packet_manifest(source["fixture"]["out"], source["path"], source["root"],
                                  source["output"], packet_version="set-v1",
                                  contract=source["fixture"]["contract"], **kwargs)


def evidence(source, imported):
    path = source["root"] / "quality.json"
    path.write_text(json.dumps({"schema_version": "packet-quality-v1",
        "packet_set_digest": imported["packet_set_digest"], "task_hash": imported["task_hash"],
        "reviewer_identity": "offline-fixture-review", "criteria_identity": "fixture-contract-v1",
        "arms": {"A": "PASS", "B": "PASS"}, "model_executed": False}), encoding="utf-8")
    return path


def assert_envelope_schema(value):
    import jsonschema
    from benchmark_core.fast_zoning import qualification_import
    schema = json.loads(Path(qualification_import.__file__).with_name("qualification-import.v1.schema.json").read_text())
    jsonschema.validate(value, schema)


def test_zero_source_packets_preserve_bytes_and_provenance_without_execution(packet_source):
    result = bind(packet_source)
    assert result["packets_imported"] is True
    assert result["packet_quality_qualified"] is False
    assert result["execution_ready"] == "NO_PACKET_QUALITY"
    assert result["packet_set_version"] == "set-v1"
    assert_envelope_schema(result)
    for arm in ("A", "B"):
        context = result["campaign_manifest"]["contexts"][arm]
        assert context["source_item_count"] == context["source_bytes"] == 0
        assert context["packet_hash"] == packet_source["manifest"][f"{arm}_PACKET_SHA256"]
        path = packet_source["output"] / context["packet_path"]
        assert path.read_bytes() == (packet_source["root"] / f"{arm}.packet").read_bytes()
    original_bytes = packet_source["path"].read_bytes()
    assert any(path.read_bytes() == original_bytes for path in packet_source["output"].rglob("*.json"))
    with pytest.raises(InvalidManifest):
        validate_manifest(packet_source["output"] / "campaign-manifest.json")


@pytest.mark.parametrize("field,value", [("TASK_ID", "WRONG"), ("TASK_SHA256", "0" * 64),
    ("EVALUATION_PLAN_DIGEST", "0" * 64), ("A_PACKET_SHA256", "0" * 64),
    ("BENCHMARK_TREE", "0" * 40), ("TARGET_HINTS", ["logic.py"])])
def test_wrong_task_or_packet_binding_rejected(packet_source, field, value):
    packet_source["manifest"][field] = value
    packet_source["path"].write_text(json.dumps(packet_source["manifest"]), encoding="utf-8")
    with pytest.raises(InvalidManifest):
        bind(packet_source)


def test_missing_packet_rejected(packet_source):
    (packet_source["root"] / "A.packet").unlink()
    with pytest.raises(InvalidManifest):
        bind(packet_source)
    candidate = packet_source["output"] / "campaign-manifest.json"
    if candidate.exists():
        with pytest.raises(InvalidManifest):
            validate_manifest(candidate)


def test_failed_replacement_never_leaves_a_ready_manifest(packet_source):
    from benchmark_core.fast_zoning.packet_import import import_packet_manifest, qualify_packet_set
    first = bind(packet_source)
    ready_dir = packet_source["root"].parent / "qualified"
    qualify_packet_set(packet_source["output"], evidence(packet_source, first), ready_dir,
                       contract=packet_source["fixture"]["contract"])
    original = (ready_dir / "campaign-manifest.json").read_bytes()
    (packet_source["root"] / "B.packet").unlink()
    destination = packet_source["root"].parent / "failed-replacement"
    with pytest.raises(InvalidManifest):
        import_packet_manifest(ready_dir, packet_source["path"], packet_source["root"], destination,
            packet_version="set-v2", contract=packet_source["fixture"]["contract"])
    assert (ready_dir / "campaign-manifest.json").read_bytes() == original
    candidate = destination / "campaign-manifest.json"
    if candidate.exists():
        with pytest.raises(InvalidManifest):
            validate_manifest(candidate)


def test_quality_must_bind_exact_pair_and_require_both_arms(packet_source):
    from benchmark_core.fast_zoning.packet_import import qualify_packet_set
    imported = bind(packet_source)
    path = evidence(packet_source, imported)
    valid = json.loads(path.read_text())
    for label, change in (("wrong-set", {"packet_set_digest": "0" * 64}),
                          ("wrong-task", {"task_hash": "0" * 64}),
                          ("one-arm", {"arms": {"A": "PASS"}}),
                          ("failed-arm", {"arms": {"A": "PASS", "B": "FAIL"}})):
        path.write_text(json.dumps({**valid, **change}), encoding="utf-8")
        with pytest.raises(InvalidManifest):
            qualify_packet_set(packet_source["output"], path, packet_source["root"].parent / label,
                               contract=packet_source["fixture"]["contract"])


def test_qualified_set_replacement_resets_gate_and_preserves_frozen_task(packet_source):
    from benchmark_core.fast_zoning.packet_import import import_packet_manifest, qualify_packet_set, validate_packet_import
    first = bind(packet_source)
    ready_dir = packet_source["root"].parent / "qualified"
    ready = qualify_packet_set(packet_source["output"], evidence(packet_source, first), ready_dir,
                                contract=packet_source["fixture"]["contract"])
    assert ready["execution_ready"] == "YES"
    assert ready["packet_quality_qualified"] is True
    assert_envelope_schema(ready)
    assert validate_manifest(ready_dir / "campaign-manifest.json")["task_id"] == "TEST-01"
    old_bytes = {p.relative_to(ready_dir): p.read_bytes() for p in ready_dir.rglob("*") if p.is_file()}
    packet = packet_source["root"] / "A.packet"
    packet.write_bytes(packet.read_bytes() + b"\nUpdated real context fixture.\n")
    updated = copy.deepcopy(packet_source["manifest"])
    updated.update(A_PACKET_SHA256=hashlib.sha256(packet.read_bytes()).hexdigest(), A_PACKET_BYTES=packet.stat().st_size)
    packet_source["path"].write_text(json.dumps(updated), encoding="utf-8")
    replacement_dir = packet_source["root"].parent / "packets-v2"
    replacement = import_packet_manifest(ready_dir, packet_source["path"], packet_source["root"],
        replacement_dir, packet_version="set-v2", contract=packet_source["fixture"]["contract"])
    assert replacement["packet_set_digest"] != first["packet_set_digest"]
    assert replacement["packet_set_version"] == "set-v2"
    assert replacement["packet_quality_qualified"] is False
    assert replacement["execution_ready"] == "NO_PACKET_QUALITY"
    assert_envelope_schema(replacement)
    for key in ("source_evaluation_plan_digest", "task_id", "task_hash", "run_order"):
        assert replacement[key] == first[key]
    assert replacement["campaign_manifest"]["evaluation_plan_digest"] == first["campaign_manifest"]["evaluation_plan_digest"]
    assert {p.relative_to(ready_dir): p.read_bytes() for p in ready_dir.rglob("*") if p.is_file()} == old_bytes
    assert validate_packet_import(ready_dir, contract=packet_source["fixture"]["contract"])["execution_ready"] == "YES"


def test_packet_quality_gate_blocks_plan_without_starting_process(packet_source, monkeypatch):
    from benchmark_core.fast_zoning import runner
    bind(packet_source)
    def forbidden(*args, **kwargs):
        pytest.fail("quality rejection must occur before OMP process")
    monkeypatch.setattr(runner, "_execute", forbidden)
    with pytest.raises(InvalidManifest):
        runner.plan_campaign(packet_source["output"] / "campaign-manifest.json",
                             packet_source["root"].parent / "campaign", "pair-001")


def test_cli_packet_import_reports_valid_provenance_and_unqualified_quality(packet_source, monkeypatch, capsys):
    from cli import fast_zoning
    from benchmark_core.fast_zoning.packet_import import import_packet_manifest
    monkeypatch.setattr(fast_zoning, "import_packet_manifest", lambda *args, **kwargs:
        import_packet_manifest(*args, **kwargs, contract=packet_source["fixture"]["contract"]))
    assert fast_zoning.main(["campaign", "import-packets", str(packet_source["fixture"]["out"]),
        str(packet_source["path"]), "--source-root", str(packet_source["root"]),
        "--packet-version", "set-v1", "--bundle-output", str(packet_source["output"])]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source_import_valid"] is True
    assert report["packets_imported"] is True
    assert report["packet_quality_qualified"] is False
    assert report["execution_ready"] == "NO_PACKET_QUALITY"


@pytest.mark.parametrize("action", ["validate", "plan"])
def test_cli_unqualified_gate_is_not_mislabeled_invalid(packet_source, action, capsys):
    from cli import fast_zoning
    bind(packet_source)
    args = ["campaign", action, str(packet_source["output"] / "campaign-manifest.json")]
    if action == "plan":
        args += ["--campaign-dir", str(packet_source["root"].parent / "campaign"), "--pair-run-id", "pair-001"]
    assert fast_zoning.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["TASK_STATUS"] == "PACKETS_IMPORTED"
    assert report["PACKETS_IMPORTED"] is True
    assert report["PACKET_QUALITY_QUALIFIED"] is False
    assert report["EXECUTION_READY"] == "NO_PACKET_QUALITY"
    assert report["MODEL_EXECUTED"] is False


def test_import_envelope_schema_rejects_contradictory_quality_state(packet_source):
    import jsonschema
    imported = bind(packet_source)
    for change in ({"execution_ready": "YES"}, {"packet_quality_qualified": True},
                   {"packets_imported": False}, {"status": "READY"}):
        with pytest.raises(jsonschema.ValidationError):
            assert_envelope_schema({**imported, **change})


def test_edited_readiness_flag_does_not_qualify_packets(packet_source):
    from benchmark_core.fast_zoning.qualification_import import validate_import
    imported = bind(packet_source)
    imported.update(packet_quality_qualified=True, execution_ready="YES", status="READY")
    (packet_source["output"] / "import.json").write_text(json.dumps(imported), encoding="utf-8")
    with pytest.raises(InvalidManifest):
        validate_import(packet_source["output"], contract=packet_source["fixture"]["contract"])


def test_execution_rechecks_quality_evidence_before_model_call(packet_source):
    from benchmark_core.fast_zoning.packet_import import qualify_packet_set
    from benchmark_core.fast_zoning.runner import execute_pair, plan_campaign
    imported = bind(packet_source)
    ready_dir = packet_source["root"].parent / "qualified"
    qualify_packet_set(packet_source["output"], evidence(packet_source, imported), ready_dir,
                       contract=packet_source["fixture"]["contract"])
    plan = plan_campaign(ready_dir / "campaign-manifest.json", packet_source["root"].parent / "campaign", "pair-001")
    manifest = json.loads((ready_dir / "campaign-manifest.json").read_text())
    ref = manifest["packet_quality_gate"]["quality_evidence"]
    (ready_dir / ref["path"]).write_text("{}", encoding="utf-8")
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        pytest.fail("changed quality evidence must block executor")
    with pytest.raises(InvalidManifest):
        execute_pair(plan["pair_dir"], authorized=True, executor=forbidden)
    assert calls == []


def test_cli_summary_keeps_pending_packet_quality_incomplete(packet_source, capsys):
    from cli import fast_zoning
    bind(packet_source)
    campaign = packet_source["root"].parent / "campaign"
    assert fast_zoning.main(["campaign", "plan", str(packet_source["output"] / "campaign-manifest.json"),
        "--campaign-dir", str(campaign), "--pair-run-id", "pair-001"]) == 2
    capsys.readouterr()
    assert fast_zoning.main(["campaign", "summarize", str(campaign)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pairs_total"] == 1
    assert result["pairs_incomplete"] == 1
    assert result["pairs_invalid"] == 0
    assert result["pairs_valid"] == 0
