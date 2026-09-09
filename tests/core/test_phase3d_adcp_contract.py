from __future__ import annotations

import pytest

from suites.coding.adcp_contract import (
    ADCP_COMMIT, ADCP_INTEGRATION, ADCP_MODEL_ROUTE, ADCP_PROVIDER_ROUTE,
    ADCP_REPOSITORY, ADCP_RUNTIME,
)
from suites.coding.phase3d_adcp_contract import (
    PHASE3D_ADCP_RECEIPT_SCHEMA,
    Phase3DADCPReceiptError,
    parse_phase3d_adcp_runner_receipt,
)


def receipt(status: str = "CANDIDATE_READY") -> dict[str, object]:
    ready = status == "CANDIDATE_READY"
    return {
        "schema": PHASE3D_ADCP_RECEIPT_SCHEMA,
        "target_runtime": {
            "repository": ADCP_REPOSITORY,
            "commit": ADCP_COMMIT,
            "runtime": ADCP_RUNTIME,
            "integration": ADCP_INTEGRATION,
        },
        "runtime_loaded": True,
        "role_ids": {
            "architect": "phase3d-architect",
            "coder": "phase3d-coder",
            "reviewer": "phase3d-reviewer",
            "verifier": "phase3d-verifier",
        },
        "role_call_counts": {
            "architect": 1,
            "coder": 1 if ready else 0,
            "reviewer": 1 if ready else 0,
            "verifier": 1 if ready else 0,
        },
        "event_sequence": ["ARCHITECT", "CODER", "REVIEWER", "VERIFIER"] if ready else ["ARCHITECT"],
        "outcome_status": status,
        "reason_code": "LOCAL_HANDOFF" if ready else "ARCHITECTURE_ASSURANCE_BLOCKED",
        "candidate_ready": ready,
        "task_completed": False,
        "model_route": ADCP_MODEL_ROUTE,
        "provider_route": ADCP_PROVIDER_ROUTE,
        "model_calls_via_budget_proxy": True,
        "upstream_provider_credential_present": False,
        "proxy_credential_present": True,
        "model_called": True,
        "session_id": "phase3d-session",
        "request_id": "phase3d-request",
        "candidate_snapshot_id": "candidate-1" if ready else None,
        "repair_count": 0,
        "scope_projection_id": "sha256:" + "a" * 64,
    }


def test_candidate_ready_is_exportable_but_not_task_completed() -> None:
    parsed = parse_phase3d_adcp_runner_receipt(receipt())
    assert parsed.exports_candidate is True
    assert parsed.candidate_ready is True
    assert parsed.task_completed is False


def test_bounded_failure_is_valid_arm_result_not_infrastructure_error() -> None:
    parsed = parse_phase3d_adcp_runner_receipt(receipt("BLOCKED_ARCHITECTURE"))
    assert parsed.exports_candidate is False
    assert parsed.candidate_ready is False
    assert parsed.candidate_snapshot_id is None


def test_nonready_receipt_cannot_claim_candidate_ready() -> None:
    raw = receipt("BUDGET_EXHAUSTED")
    raw["candidate_ready"] = True
    with pytest.raises(Phase3DADCPReceiptError, match="exactly match"):
        parse_phase3d_adcp_runner_receipt(raw)


def test_paid_receipt_rejects_upstream_provider_key_visibility() -> None:
    raw = receipt()
    raw["upstream_provider_credential_present"] = True
    with pytest.raises(Phase3DADCPReceiptError, match="must not possess"):
        parse_phase3d_adcp_runner_receipt(raw)


def test_ready_receipt_requires_complete_role_subsequence() -> None:
    raw = receipt()
    raw["event_sequence"] = ["ARCHITECT", "CODER", "VERIFIER"]
    with pytest.raises(Phase3DADCPReceiptError, match="subsequence"):
        parse_phase3d_adcp_runner_receipt(raw)
