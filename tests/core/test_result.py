from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "benchmark_core"))

from benchmark_core.result import HardGate, OracleResult, RunResult, RunStatus, StageResult, SuiteResult, SystemObservation

D = "sha256:" + "2" * 64
E = "cas:sha256:" + "3" * 64


def test_run_status_taxonomy_is_exact() -> None:
    assert {status.value for status in RunStatus} == {
        "PASS", "FAIL", "INFRA_FAILURE", "BASELINE_BROKEN", "UNSUPPORTED",
        "SKIPPED", "INVALID_EXPERIMENT",
    }


def test_six_noncompensable_gates_are_exact() -> None:
    assert {gate.value for gate in HardGate} == {
        "false_safe_certificate", "unauthorized_cross_zone_write",
        "half_applied_transaction", "accepted_stale_candidate",
        "lost_required_verification", "evidence_integrity_failure",
    }
    oracle = OracleResult("independent-check", "v1", RunStatus.PASS, evidence_refs=(E,))
    with pytest.raises(ValueError, match="cannot have PASS"):
        SuiteResult("harness", "v1", "PASS", (oracle,), (HardGate.HALF_APPLIED_TRANSACTION,))


def test_observation_oracle_stage_and_suite_are_independent_immutable_records() -> None:
    source = {"latency_ms": [10, 11]}
    observation = SystemObservation("PASS", output_artifact="cas:" + D, attributes=source)
    source["latency_ms"].append(12)
    oracle = OracleResult("functional", "v3", "PASS", {"accuracy": 1.0}, (E,))
    stage = StageResult("execute", "PASS", observation, (oracle,), (E,))
    suite = SuiteResult("zone-development", "v2", "PASS", (oracle,), metrics={"completion_rate": 1.0}, stage_results=(stage,))
    assert suite.passed
    assert observation.attributes["latency_ms"] == (10, 11)
    assert suite.oracle_results[0] is oracle


def test_suite_cannot_pass_failed_oracle_and_evidence_must_be_cas_backed() -> None:
    failed_oracle = OracleResult("functional", "v1", "FAIL")
    with pytest.raises(ValueError, match="independent oracle"):
        SuiteResult("suite", "v1", "PASS", (failed_oracle,))
    with pytest.raises(ValueError, match="CAS-backed"):
        OracleResult("functional", "v1", "PASS", evidence_refs=(D,))


def test_global_autonomous_dev_score_is_forbidden() -> None:
    with pytest.raises(ValueError, match="AUTONOMOUS_DEV_SCORE"):
        SuiteResult("full-system", "v1", "PASS", (), metrics={"AUTONOMOUS_DEV_SCORE": 87.3})
    with pytest.raises(ValueError, match="AUTONOMOUS_DEV_SCORE"):
        OracleResult("bad-oracle", "v1", "PASS", {"autonomous-dev-score": 1})


def test_run_result_preserves_suite_results_without_compensation() -> None:
    passed = SuiteResult("zoning", "v1", "PASS", ())
    failed = SuiteResult("harness", "v1", "FAIL", (), (HardGate.LOST_REQUIRED_VERIFICATION,))
    with pytest.raises(ValueError, match="every independent suite"):
        RunResult("run-1", D, "PASS", (passed, failed))
    result = RunResult("run-1", D, "FAIL", (passed, failed))
    assert result.status is RunStatus.FAIL
    assert len(result.suite_results) == 2
