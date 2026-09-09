import pytest

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import (
    ModelAccountingError,
    ModelBudgetExceeded,
    ModelBudgetGateway,
    ModelUsage,
)


def budget(**overrides):
    values = dict(
        input_token_cap=100,
        output_token_cap=80,
        total_model_token_cap=150,
        max_requests=3,
        wall_time_seconds=60,
        patch_byte_cap=1000,
    )
    values.update(overrides)
    return BudgetManifest(**values)


def test_shared_gateway_accounts_primary_and_diagnostic_usage_without_double_counting():
    gateway = ModelBudgetGateway(budget())
    ticket = gateway.admit_request(40)
    snapshot = gateway.settle(
        ticket,
        ModelUsage(
            input_tokens=30,
            output_tokens=20,
            reasoning_tokens=7,
            cache_tokens=11,
            cost_usd_micros=250,
        ),
    )

    assert snapshot.requests == 1
    assert snapshot.input_tokens == 30
    assert snapshot.output_tokens == 20
    assert snapshot.total_model_tokens == 50
    assert snapshot.reasoning_tokens == 7
    assert snapshot.cache_tokens == 11
    assert snapshot.cost_usd_micros == 250
    assert snapshot.reserved_output_tokens == 0
    assert not snapshot.exhausted


def test_concurrent_output_reservations_cannot_exceed_shared_cap():
    gateway = ModelBudgetGateway(budget(output_token_cap=50, total_model_token_cap=50))
    first = gateway.admit_request(40)
    second = gateway.admit_request(40)

    assert first.reserved_output_tokens == 40
    assert second.reserved_output_tokens == 10
    assert gateway.snapshot().reserved_output_tokens == 50

    with pytest.raises(ModelBudgetExceeded):
        gateway.admit_request(1)


def test_provider_overshoot_is_recorded_then_marks_trial_exceeded():
    gateway = ModelBudgetGateway(budget(total_model_token_cap=40))
    ticket = gateway.admit_request(20)

    with pytest.raises(ModelBudgetExceeded) as raised:
        gateway.settle(ticket, ModelUsage(input_tokens=30, output_tokens=20))

    assert raised.value.snapshot.total_model_tokens == 50
    assert "total_model_token_cap" in raised.value.snapshot.violations
    with pytest.raises(ModelBudgetExceeded):
        gateway.admit_request(1)


def test_failed_provider_attempt_releases_reservation_but_keeps_request_count():
    gateway = ModelBudgetGateway(budget(max_requests=1))
    ticket = gateway.admit_request(50)
    snapshot = gateway.cancel(ticket)

    assert snapshot.requests == 1
    assert snapshot.reserved_output_tokens == 0
    with pytest.raises(ModelBudgetExceeded) as raised:
        gateway.admit_request(1)
    assert "max_requests" in raised.value.snapshot.violations


def test_ticket_cannot_be_settled_twice():
    gateway = ModelBudgetGateway(budget())
    ticket = gateway.admit_request(10)
    gateway.settle(ticket, ModelUsage(1, 1))

    with pytest.raises(ModelAccountingError):
        gateway.settle(ticket, ModelUsage(1, 1))
    assert not gateway.snapshot().accounting_valid


def test_wall_time_is_a_hard_admission_gate():
    now = [0.0]
    gateway = ModelBudgetGateway(budget(wall_time_seconds=5), clock=lambda: now[0])
    now[0] = 6.0

    with pytest.raises(ModelBudgetExceeded) as raised:
        gateway.admit_request(1)
    assert "wall_time_seconds" in raised.value.snapshot.violations
