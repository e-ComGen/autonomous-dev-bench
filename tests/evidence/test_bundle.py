import json

import pytest

from benchmark_core.cas import FileSystemCAS
from benchmark_core.evidence import EvidenceBundleVerifier, EvidenceBundleWriter, EvidenceIntegrityError


def manifest(run_id: str, evidence_ref: str) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "schema_version": "1", "run_id": run_id, "experiment_id": "exp_1",
        "versions": {"benchmark_spec": "1", "runner": "1", "adapter": "1", "suite": "1", "policy": "1", "acceptance": "1"},
        "input": {"project_digest": digest, "task_digest": digest, "checkpoint_digest": digest, "environment_digest": digest},
        "system": {"system_id": "sut", "commit": "b" * 40, "configuration_digest": digest},
        "scenario": {"scenario_id": "s", "scenario_version": "1", "content_digest": digest},
        "suite_results": {"suite": {"suite_version": "1", "status": "PASS", "oracle_results": {"oracle": {"oracle_version": "1", "status": "PASS", "evidence_refs": [evidence_ref]}}, "suite_gate_outcomes": {}, "global_gate_outcomes": {}}},
        "metrics": {}, "provenance": {"host": "test"},
    }


def test_bundle_reference_integrity_and_replay(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas")
    external = cas.put_text("oracle evidence")
    bundle = tmp_path / "run"
    writer = EvidenceBundleWriter(bundle, cas)
    writer.write_json("environment.json", {"fingerprint": "sha256:" + "a" * 64})
    writer.add_stage({"component": "oracle", "status": "PASS", "evidence_refs": [external]})
    writer.finalize(manifest("br_1", external),
                    replay_argv=("python", "-c", "print('replay')"), replay_environment={"SEED": "1"})
    assert writer.root_digest is not None
    verified_manifest = EvidenceBundleVerifier(cas).verify(bundle, expected_root=writer.root_digest)
    assert "replay.sh" in verified_manifest["files"] and "replay.bat" in verified_manifest["files"]
    assert "shell=False" not in (bundle / "replay.sh").read_text(encoding="utf-8")


def test_verifier_rejects_unlisted_bundle_entries(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas-extra")
    bundle = tmp_path / "bundle-extra"
    writer = EvidenceBundleWriter(bundle, cas)
    proof = cas.put_text("proof")
    writer.add_stage({"component": "stage", "status": "PASS", "evidence_refs": [proof]})
    writer.finalize(manifest("br_extra", proof))
    (bundle / "unlisted.txt").write_text("not committed", encoding="utf-8")
    with pytest.raises(EvidenceIntegrityError, match="exactly match"):
        EvidenceBundleVerifier(cas).verify(bundle, expected_root=writer.root_digest)


def test_bundle_detects_changed_file_and_broken_reference(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas"); bundle = tmp_path / "run"
    writer = EvidenceBundleWriter(bundle, cas)
    proof = cas.put_text("proof")
    writer.add_stage({"component": "stage", "status": "PASS", "evidence_refs": [proof]})
    writer.finalize(manifest("br_2", proof))
    (bundle / "stages" / "stage.json").write_text("{}\n", encoding="utf-8")
    assert writer.root_digest is not None
    with pytest.raises(EvidenceIntegrityError): EvidenceBundleVerifier(cas).verify(bundle, expected_root=writer.root_digest)
