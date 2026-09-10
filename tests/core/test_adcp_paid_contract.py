from __future__ import annotations

import pytest

from suites.coding.adcp_contract import (
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_INTERNAL_EVALUATION_POLICY,
    ADCP_MODEL_ROUTE,
    ADCP_PAID_RECEIPT_SCHEMA,
    ADCP_PROVIDER_ROUTE,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
    ADCP_SCOPE_POLICY,
    ADCPReceiptError,
    parse_adcp_paid_runner_receipt,
)


def receipt(**overrides):
    value = {
        "schema": ADCP_PAID_RECEIPT_SCHEMA,
        "target_runtime": {
            "repository": ADCP_REPOSITORY,
            "commit": ADCP_COMMIT,
            "runtime": ADCP_RUNTIME,
            "integration": ADCP_INTEGRATION,
        },
        "runtime_loaded": True,
        "fake_runtime": False,
        "role_ids": {"architect": "a", "coder": "c", "reviewer": "r", "verifier": "v"},
        "role_call_counts": {"architect": 1, "coder": 1, "reviewer": 1, "verifier": 1},
        "event_sequence": ["ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "CANDIDATE_READY"],
        "outcome_status": "CANDIDATE_READY",
        "candidate_ready": True,
        "task_completed": False,
        "model_route": ADCP_MODEL_ROUTE,
        "provider_route": ADCP_PROVIDER_ROUTE,
        "model_calls_via_budget_proxy": True,
        "upstream_provider_credential_present": False,
        "proxy_credential_present": True,
        "model_called": True,
        "session_id": "paid-session",
        "request_id": "paid-request",
        "candidate_snapshot_id": "candidate-1",
        "repair_count": 0,
        "scope_policy": ADCP_SCOPE_POLICY,
        "scope_digest": "sha256:" + "a" * 64,
        "write_scope_paths": ["package/source.py"],
        "internal_evaluation_policy": ADCP_INTERNAL_EVALUATION_POLICY,
    }
    value.update(overrides)
    return value


def test_paid_receipt_accepts_candidate_ready():
    parsed = parse_adcp_paid_runner_receipt(receipt())
    assert parsed.candidate_ready
    assert parsed.outcome_status == "CANDIDATE_READY"


def test_paid_receipt_accepts_bounded_task_failure_without_candidate():
    raw = receipt(
        outcome_status="BLOCKED_REQUIREMENT",
        candidate_ready=False,
        candidate_snapshot_id=None,
        role_call_counts={"architect": 1, "coder": 0, "reviewer": 0, "verifier": 0},
        event_sequence=["ARCHITECT"],
    )
    parsed = parse_adcp_paid_runner_receipt(raw)
    assert not parsed.candidate_ready
    assert parsed.candidate_snapshot_id is None


def test_paid_receipt_rejects_failure_disguised_as_ready():
    with pytest.raises(ADCPReceiptError, match="candidate_ready disagrees"):
        parse_adcp_paid_runner_receipt(receipt(outcome_status="FAILED_BOUNDED"))


def test_paid_receipt_never_accepts_task_completion_authority():
    with pytest.raises(ADCPReceiptError, match="TASK_COMPLETED"):
        parse_adcp_paid_runner_receipt(receipt(task_completed=True))


def test_paid_receipt_binds_scope_and_rejects_unknown_fields():
    with pytest.raises(ADCPReceiptError, match="scope_digest"):
        parse_adcp_paid_runner_receipt(receipt(scope_digest="not-a-digest"))
    with pytest.raises(ADCPReceiptError, match="write-scope policy"):
        parse_adcp_paid_runner_receipt(receipt(scope_policy="phase3d-public-static-python-scope-v1"))
    with pytest.raises(ADCPReceiptError, match="internal handoff policy"):
        parse_adcp_paid_runner_receipt(
            receipt(internal_evaluation_policy="phase3d-public-handoff-nonempty-change-v1")
        )
    raw = receipt()
    raw["hidden_answer"] = True
    with pytest.raises(ADCPReceiptError, match="fields mismatch"):
        parse_adcp_paid_runner_receipt(raw)
