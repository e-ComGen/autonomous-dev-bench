from __future__ import annotations

import pytest

from suites.coding.adcp_contract import (
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_MODEL_ROUTE,
    ADCP_PROVIDER_ROUTE,
    ADCP_RECEIPT_SCHEMA,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
    ADCPReceiptError,
    parse_adcp_runner_receipt,
)


def _receipt(**overrides):
    receipt = {
        "schema": ADCP_RECEIPT_SCHEMA,
        "target_runtime": {
            "repository": ADCP_REPOSITORY,
            "commit": ADCP_COMMIT,
            "runtime": ADCP_RUNTIME,
            "integration": ADCP_INTEGRATION,
        },
        "runtime_loaded": False,
        "fake_runtime": True,
        "role_ids": {
            "architect": "architect-1",
            "coder": "coder-1",
            "reviewer": "reviewer-1",
            "verifier": "verifier-1",
        },
        "role_call_counts": {
            "architect": 1,
            "coder": 2,
            "reviewer": 2,
            "verifier": 2,
        },
        "event_sequence": [
            "ARCHITECT",
            "CODER",
            "REVIEWER",
            "VERIFIER",
            "BADC_REPAIR",
            "CODER",
            "REVIEWER",
            "VERIFIER",
            "CANDIDATE_READY",
        ],
        "outcome_status": "CANDIDATE_READY",
        "candidate_ready": True,
        "task_completed": False,
        "model_route": ADCP_MODEL_ROUTE,
        "provider_route": ADCP_PROVIDER_ROUTE,
        "model_calls_via_budget_proxy": True,
        "upstream_provider_credential_present": False,
        "proxy_credential_present": True,
        "model_called": False,
        "session_id": "qualification-session",
        "request_id": "qualification-request",
        "candidate_snapshot_id": "candidate-after-repair",
        "repair_count": 1,
    }
    receipt.update(overrides)
    return receipt


def test_fake_qualification_receipt_accepts_explicit_bounded_repair_cycle() -> None:
    parsed = parse_adcp_runner_receipt(
        _receipt(),
        allow_fake_runtime=True,
        require_repair_cycle=True,
    )

    assert parsed.fake_runtime
    assert not parsed.runtime_loaded
    assert parsed.repair_count == 1
    assert parsed.candidate_ready
    assert not parsed.task_completed


def test_fake_runtime_is_rejected_by_production_mode() -> None:
    with pytest.raises(ADCPReceiptError, match="forbidden in production"):
        parse_adcp_runner_receipt(_receipt())


def test_production_receipt_requires_real_pinned_runtime_loaded() -> None:
    receipt = _receipt(fake_runtime=False, runtime_loaded=True, repair_count=0)
    receipt["role_call_counts"] = {name: 1 for name in ("architect", "coder", "reviewer", "verifier")}
    receipt["event_sequence"] = ["ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "CANDIDATE_READY"]
    parsed = parse_adcp_runner_receipt(receipt)
    assert parsed.runtime_loaded
    assert not parsed.fake_runtime


def test_private_runtime_pin_mismatch_fails_closed() -> None:
    receipt = _receipt()
    receipt["target_runtime"] = dict(receipt["target_runtime"], commit="0" * 40)
    with pytest.raises(ADCPReceiptError, match="different ADCP production identity"):
        parse_adcp_runner_receipt(receipt, allow_fake_runtime=True)


def test_four_role_identities_must_be_distinct() -> None:
    receipt = _receipt()
    receipt["role_ids"] = dict(receipt["role_ids"], reviewer="coder-1")
    with pytest.raises(ADCPReceiptError, match="identities must be distinct"):
        parse_adcp_runner_receipt(receipt, allow_fake_runtime=True)


def test_candidate_ready_never_equals_task_completed() -> None:
    with pytest.raises(ADCPReceiptError, match="forbids TASK_COMPLETED"):
        parse_adcp_runner_receipt(_receipt(task_completed=True), allow_fake_runtime=True)


def test_budget_proxy_and_upstream_credential_boundary_is_hard() -> None:
    with pytest.raises(ADCPReceiptError, match="budget proxy"):
        parse_adcp_runner_receipt(
            _receipt(model_calls_via_budget_proxy=False), allow_fake_runtime=True
        )
    with pytest.raises(ADCPReceiptError, match="upstream provider credential"):
        parse_adcp_runner_receipt(
            _receipt(upstream_provider_credential_present=True), allow_fake_runtime=True
        )
    with pytest.raises(ADCPReceiptError, match="proxy credential"):
        parse_adcp_runner_receipt(
            _receipt(proxy_credential_present=False), allow_fake_runtime=True
        )


def test_fake_qualification_cannot_claim_model_call() -> None:
    with pytest.raises(ADCPReceiptError, match="must not call a model"):
        parse_adcp_runner_receipt(_receipt(model_called=True), allow_fake_runtime=True)


def test_repair_qualification_requires_second_coder_reviewer_verifier_cycle() -> None:
    receipt = _receipt()
    receipt["event_sequence"] = ["ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "CANDIDATE_READY"]
    with pytest.raises(ADCPReceiptError, match="subsequence"):
        parse_adcp_runner_receipt(
            receipt,
            allow_fake_runtime=True,
            require_repair_cycle=True,
        )


def test_unknown_receipt_fields_are_rejected() -> None:
    receipt = _receipt()
    receipt["pretend_success"] = True
    with pytest.raises(ADCPReceiptError, match="fields mismatch"):
        parse_adcp_runner_receipt(receipt, allow_fake_runtime=True)
