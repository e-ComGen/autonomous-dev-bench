"""Offline contracts for qualification import; no OMP or benchmark models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import git
from benchmark_core.fast_zoning.manifest import InvalidManifest, validate_manifest


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


@pytest.fixture
def qualification(tmp_path: Path, source_repo: dict, task_manifest: Path, monkeypatch):
    repo = tmp_path / "qualification"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Offline fixture")
    git(repo, "config", "core.autocrlf", "false")
    root = repo / "src/omp_zones/evaluation/expansion"
    task = root / "TEST-01"
    task.mkdir(parents=True)
    from benchmark_core.fast_zoning import qualification_evaluator
    module_hashes = {}
    for name in qualification_evaluator.SOURCE_MODULES:
        module = repo / "src/omp_zones" / name
        module.write_text("# Offline fixture module, never executed\n", encoding="utf-8")
        module_hashes[name] = hashlib.sha256(module.read_bytes()).hexdigest()
    monkeypatch.setattr(qualification_evaluator, "SOURCE_MODULES", module_hashes)
    baseline = json.loads(task_manifest.read_text())
    artifact = task / "oracle.py"
    artifact.write_text("print('fixture oracle')\n", encoding="utf-8")
    payload_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    categories = ["EXISTING_SUITE", "NARROW_ORACLE", "DIFFERENTIAL_CHECK",
                  "METAMORPHIC_CHECK", "CROSS_COMPONENT_CHECK"]
    evaluators = [
        {"id": "test-existing", "category": categories[0], "runner": "pytest", "args": ["tests"]},
        {"id": "test-oracle", "category": categories[1], "runner": "frozen_oracle",
         "oracle_path": "oracle.py", "oracle_sha256": payload_hash}]
    for category in categories[2:]:
        evaluators.append({"id": category.lower(), "category": category, "runner": "differential",
                           **{f"{name}_path": "oracle.py" for name in ("cases", "reference", "probe")},
                           **{f"{name}_sha256": payload_hash for name in ("cases", "reference", "probe")}})
    plan = {"schema_version": 1, "phase": "PREDECLARED", "benchmark_id": "fixture",
            "benchmark_head": source_repo["buggy_head"], "benchmark_tree": source_repo["buggy_tree"],
            "reference_head": source_repo["clean_head"], "reference_tree": source_repo["clean_tree"],
            "task_text": baseline["task_text"], "task_sha256": baseline["task_hash"], "target_hints": [],
            "evaluators": evaluators,
            **{f"required_{key}": True for key in ("existing_suite", "targeted_oracle",
                   "differential_checks", "metamorphic_checks", "cross_component_checks")}}
    statuses = {row["id"]: "PASS" for row in evaluators}
    evidence = {"TASK_ID": "TEST-01", "TASK_EXECUTION_READY": "YES", "MODEL_EXECUTED": False,
                "KNOWN_FIX_RESET": "YES", "TARGET_HINTS": [], "TASK_TEXT": plan["task_text"],
                "TASK_HASH": plan["task_sha256"], "CLEAN_HEAD": source_repo["clean_head"],
                "CLEAN_TREE": source_repo["clean_tree"], "BUGGY_HEAD": source_repo["buggy_head"],
                "BUGGY_TREE": source_repo["buggy_tree"], "EVALUATION_PLAN_DIGEST": digest(plan),
                "CLEAN_EVALUATION": "PASS", "BUGGY_EVALUATION": "FAIL", "KNOWN_FIX_EVALUATION": "PASS",
                "HIDDEN_ROOT_CAUSE": "PRIVATE GOLD CAUSE", "KNOWN_CORRECT_FIX": "PRIVATE GOLD PATCH",
                "EXPECTED_FIX_SCOPE": "PRIVATE SCOPE", "AUTO_ZONING_AVAILABLE": True,
                "AUTOZONING": {"analysis_digest": "sha256:" + "a" * 64, "snapshot_ref": "fixture"},
                "PRIMARY_ZONE": {"zone_id": "fixture-zone", "artifact_paths": ["logic.py"]},
                "DEPENDENCY_ZONE_COVERAGE": {"logic.py": "UNATTRIBUTED"},
                "EVALUATIONS": {"clean": {"EVALUATOR_STATUS": statuses, "SEMANTIC_SUCCESS": "YES"},
                                "known-fix": {"EVALUATOR_STATUS": statuses, "SEMANTIC_SUCCESS": "YES"},
                                "buggy": {"EVALUATOR_STATUS": {**statuses, "test-oracle": "FAIL"},
                                          "SEMANTIC_SUCCESS": "NO"}}}
    return {"repo": repo, "benchmark": source_repo["repo"], "plan": plan, "evidence": evidence,
            "root": root, "task": task, "contexts": baseline["contexts"], "out": tmp_path / "import"}


def commit_source(fixture: dict):
    from benchmark_core.fast_zoning.qualification_import import SourceContract
    (fixture["task"] / "evaluation-plan.json").write_text(json.dumps(fixture["plan"]), encoding="utf-8")
    (fixture["root"] / "readiness.json").write_text(json.dumps({"TEST-01": fixture["evidence"]}), encoding="utf-8")
    git(fixture["repo"], "add", ".")
    if git(fixture["repo"], "status", "--porcelain"):
        git(fixture["repo"], "commit", "-m", "qualification fixture")
    return SourceContract(head=git(fixture["repo"], "rev-parse", "HEAD"),
                          tree=git(fixture["repo"], "rev-parse", "HEAD^{tree}"),
                          evaluation_digests={"TEST-01": digest(fixture["plan"])})


def import_fixture(fixture: dict, **kwargs):
    from benchmark_core.fast_zoning.qualification_import import import_qualification
    contract = commit_source(fixture)
    fixture["contract"] = contract
    result = import_qualification(fixture["repo"], fixture["benchmark"], "TEST-01", fixture["out"],
                                  run_order_seed="fixture-order", contract=contract, **kwargs)
    return result


def test_qualified_import_retains_source_digest_and_missing_packet_state(qualification):
    result = import_fixture(qualification)
    assert result["source_evaluation_plan_digest"] == digest(qualification["plan"])
    assert result["campaign_manifest_digest"] != result["source_evaluation_plan_digest"]
    assert result["source_import_valid"] is True
    assert result["execution_ready"] == "NO_MISSING_PACKETS"
    assert result["status"] == "IMPORTED_NOT_EXECUTABLE"


@pytest.mark.parametrize("field,value", [("TASK_EXECUTION_READY", "NO"), ("MODEL_EXECUTED", True),
                                         ("KNOWN_FIX_RESET", "NO"), ("TASK_HASH", "0" * 64)])
def test_unqualified_or_wrong_task_evidence_rejected(qualification, field, value):
    qualification["evidence"][field] = value
    with pytest.raises(InvalidManifest):
        import_fixture(qualification)


def test_source_evaluator_hash_mismatch_rejected(qualification):
    (qualification["task"] / "oracle.py").write_text("tampered payload", encoding="utf-8")
    with pytest.raises(InvalidManifest):
        import_fixture(qualification)


def test_source_digest_mismatch_rejected(qualification):
    qualification["evidence"]["EVALUATION_PLAN_DIGEST"] = "0" * 64
    with pytest.raises(InvalidManifest):
        import_fixture(qualification)


def test_optional_evaluator_is_retained_without_becoming_required(qualification):
    qualification["plan"]["required_metamorphic_checks"] = False
    qualification["evidence"]["EVALUATION_PLAN_DIGEST"] = digest(qualification["plan"])
    result = import_fixture(qualification)
    rows = result["campaign_manifest"]["evaluation_plan"]["evaluators"]
    optional = next(row for row in rows if row["id"] == "metamorphic_check")
    assert optional["required"] is False
    assert len(rows) == 5


def test_import_is_deterministic_and_required_evaluators_survive(qualification):
    first = import_fixture(qualification)
    second_fixture = dict(qualification, out=qualification["out"].with_name("second-import"))
    second = import_fixture(second_fixture)
    assert first["source_evaluation_plan_digest"] == second["source_evaluation_plan_digest"]
    assert first["campaign_manifest_digest"] == second["campaign_manifest_digest"]
    assert first["import_binding_digest"] == second["import_binding_digest"]
    campaign_rows = first["campaign_manifest"]["evaluation_plan"]["evaluators"]
    assert {row["id"] for row in campaign_rows if row["required"]} == {
        row["id"] for row in qualification["plan"]["evaluators"]}
    assert len(campaign_rows) == len(qualification["plan"]["evaluators"])


def test_gold_is_absent_from_public_manifest_and_packet_request(qualification):
    result = import_fixture(qualification)
    visible = json.dumps([result["model_visible_manifest"], result["campaign_manifest"]])
    request = (qualification["out"] / "packet-build-request.json").read_text(encoding="utf-8")
    for secret in ("PRIVATE GOLD CAUSE", "PRIVATE GOLD PATCH", "PRIVATE SCOPE",
                   "HIDDEN_ROOT_CAUSE", "KNOWN_CORRECT_FIX"):
        assert secret not in visible
        assert secret not in request
    private = (qualification["out"] / "private/qualification.json").read_text(encoding="utf-8")
    assert "UNATTRIBUTED" in private


def test_post_import_tamper_rejected(qualification):
    from benchmark_core.fast_zoning.qualification_import import validate_import
    import_fixture(qualification)
    envelope_path = qualification["out"] / "import.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["campaign_manifest"]["task_text"] = "different task"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(InvalidManifest):
        validate_import(qualification["out"], contract=qualification["contract"])


def test_missing_packets_cannot_enter_original_executable_validator(qualification):
    result = import_fixture(qualification)
    task = qualification["out"] / "not-executable-task.json"
    task.write_text(json.dumps(result["campaign_manifest"]), encoding="utf-8")
    with pytest.raises(InvalidManifest):
        validate_manifest(task)


def test_real_packet_bytes_bind_without_model_process(qualification, monkeypatch):
    from benchmark_core.fast_zoning import runner
    from benchmark_core.fast_zoning.qualification_import import attach_packets
    def forbidden(*args, **kwargs):
        pytest.fail("import/bind must never run OMP")
    monkeypatch.setattr(runner, "execute_pair", forbidden)
    import_fixture(qualification)
    output = qualification["out"].with_name("bound-import")
    result = attach_packets(qualification["out"], qualification["contexts"], output,
                            contract=qualification["contract"])
    assert result["execution_ready"] == "NO_PACKET_QUALITY"
    assert result["packets_imported"] is True
    assert result["packet_quality_qualified"] is False
    assert result["source_evaluation_plan_digest"] == digest(qualification["plan"])
    task = output / "test-executable.json"
    task.write_text(json.dumps(result["campaign_manifest"]), encoding="utf-8")
    with pytest.raises(InvalidManifest):
        validate_manifest(task)
    original = json.loads((qualification["out"] / "import.json").read_text())
    assert original["execution_ready"] == "NO_MISSING_PACKETS"


def test_historical_pair_fixtures_remain_frozen():
    fixture = Path(__file__).parent / "fixtures/pairs123.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == "534e2a9e8734c1bdfcc1b0dfe1cdd1a5794e5d00c6ec85c995135e5ccb94f58b"


def test_failed_inline_packet_import_cannot_publish_executable_manifest(qualification):
    Path(qualification["contexts"]["B"]["packet_path"]).unlink()
    with pytest.raises((InvalidManifest, OSError)):
        import_fixture(qualification, contexts=qualification["contexts"])
    candidate = qualification["out"] / "campaign-manifest.json"
    if candidate.exists():
        with pytest.raises(InvalidManifest):
            validate_manifest(candidate)


def test_unknown_source_evaluator_cannot_disappear(qualification):
    qualification["plan"]["evaluators"][0]["category"] = "UNDECLARED_CHECK"
    qualification["evidence"]["EVALUATION_PLAN_DIGEST"] = digest(qualification["plan"])
    with pytest.raises(InvalidManifest):
        import_fixture(qualification)


def test_unicode_source_digest_uses_original_qualification_canonicalization(qualification):
    text = "Restore café handling without changing other behavior."
    task_hash = hashlib.sha256(text.encode()).hexdigest()
    qualification["plan"].update(task_text=text, task_sha256=task_hash)
    qualification["evidence"].update(TASK_TEXT=text, TASK_HASH=task_hash,
                                   EVALUATION_PLAN_DIGEST=digest(qualification["plan"]))
    result = import_fixture(qualification)
    assert result["source_evaluation_plan_digest"] == digest(qualification["plan"])
    assert result["model_visible_manifest"]["task_text"] == text


def test_validate_import_cli_reports_valid_missing_packets(qualification, monkeypatch, capsys):
    from cli import fast_zoning
    from benchmark_core.fast_zoning.qualification_import import validate_import
    import_fixture(qualification)
    monkeypatch.setattr(fast_zoning, "validate_import",
                        lambda path: validate_import(path, contract=qualification["contract"]))
    assert fast_zoning.main(["campaign", "validate-import", str(qualification["out"])]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source_import_valid"] is True
    assert report["execution_ready"] == "NO_MISSING_PACKETS"


def test_hidden_gold_packet_cannot_become_executable(qualification):
    from benchmark_core.fast_zoning.qualification_import import attach_packets
    import_fixture(qualification)
    packet = Path(qualification["contexts"]["A"]["packet_path"])
    packet.write_text("PRIVATE GOLD PATCH", encoding="utf-8")
    qualification["contexts"]["A"].update(packet_hash=hashlib.sha256(packet.read_bytes()).hexdigest(),
                                          packet_bytes=packet.stat().st_size)
    with pytest.raises(InvalidManifest):
        attach_packets(qualification["out"], qualification["contexts"],
                       qualification["out"].with_name("leaking"), contract=qualification["contract"])


def test_emitted_import_and_packet_request_conform_to_packaged_schemas(qualification):
    import jsonschema
    from benchmark_core.fast_zoning import qualification_import
    envelope = import_fixture(qualification)
    schemas = Path(qualification_import.__file__).parent
    request = json.loads((qualification["out"] / "packet-build-request.json").read_text())
    for name, value in (("qualification-import.v1.schema.json", envelope),
                        ("packet-build-request.v1.schema.json", request)):
        schema = json.loads((schemas / name).read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(value, schema)
    output_schema = json.loads((schemas / "packet-build-output.v1.schema.json").read_text())
    assert request["output_schema"] == output_schema
    jsonschema.Draft202012Validator.check_schema(output_schema)
    jsonschema.validate(qualification["contexts"], output_schema)
    invalid = json.loads(json.dumps(qualification["contexts"]))
    del invalid["B"]["zoning"]["snapshot_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, output_schema)
