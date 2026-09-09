from __future__ import annotations

import pytest

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import (
    BudgetAccountingError,
    BudgetExceeded,
    ModelBudgetGateway,
    ModelUsage,
)


def _budget(**overrides: int) -> BudgetManifest:
    values = {
        "input_token_cap": 100,
        "output_token_cap": 80,
        "total_model_token_cap": 150,
        "max_requests": 2,
        "wall_time_seconds": 60,
        "patch_byte_cap": 1000,
    }
    values.update(overrides)
    return BudgetManifest(**values)


def test_reservation_enforces_primary_total_budget_before_dispatch() -> None:
    gateway = ModelBudgetGateway(_budget())
    first = gateway.reserve(input_tokens=60, max_output_tokens=30)

    with pytest.raises(BudgetExceeded, match="total_model_token_cap"):
        gateway.reserve(input_tokens=50, max_output_tokens=20)

    assert gateway.snapshot().open_reservations == 1
    gateway.cancel(first)


def test_commit_refunds_unused_reservation_capacity_and_records_secondary_usage() -> None:
    gateway = ModelBudgetGateway(_budget())
    reservation = gateway.reserve(input_tokens=60, max_output_tokens=30)

    snapshot = gateway.commit(
        reservation,
        ModelUsage(
            input_tokens=50,
            output_tokens=10,
            total_model_tokens=60,
            reasoning_tokens=4,
            cache_tokens=7,
            cost_usd=0.012,
            wall_time_ms=321,
        ),
    )

    assert snapshot.input_tokens == 50
    assert snapshot.output_tokens == 10
    assert snapshot.total_model_tokens == 60
    assert snapshot.reasoning_tokens == 4
    assert snapshot.cache_tokens == 7
    assert snapshot.cost_usd == pytest.approx(0.012)
    assert snapshot.wall_time_ms == 321
    assert snapshot.requests == 1
    assert snapshot.open_reservations == 0
    assert snapshot.reserved_input_tokens == 0
    assert snapshot.reserved_output_tokens == 0

    second = gateway.reserve(input_tokens=50, max_output_tokens=20)
    assert second.reserved_total_tokens == 70


def test_request_cap_counts_committed_calls_and_open_reservations() -> None:
    gateway = ModelBudgetGateway(_budget(max_requests=2, total_model_token_cap=300))
    first = gateway.reserve(input_tokens=10, max_output_tokens=10)
    second = gateway.reserve(input_tokens=10, max_output_tokens=10)

    with pytest.raises(BudgetExceeded, match="max_requests"):
        gateway.reserve(input_tokens=1, max_output_tokens=1)

    gateway.cancel(second)
    gateway.commit(first, ModelUsage(input_tokens=10, output_tokens=5, total_model_tokens=15))
    replacement = gateway.reserve(input_tokens=10, max_output_tokens=10)
    gateway.commit(replacement, ModelUsage(input_tokens=10, output_tokens=5, total_model_tokens=15))

    with pytest.raises(BudgetExceeded, match="max_requests"):
        gateway.reserve(input_tokens=1, max_output_tokens=1)


def test_accounting_mismatch_fails_closed_without_losing_reservation() -> None:
    gateway = ModelBudgetGateway(_budget())
    reservation = gateway.reserve(input_tokens=20, max_output_tokens=10)

    with pytest.raises(BudgetAccountingError, match="output tokens"):
        gateway.commit(
            reservation,
            ModelUsage(input_tokens=20, output_tokens=11, total_model_tokens=31),
        )

    snapshot = gateway.snapshot()
    assert snapshot.requests == 0
    assert snapshot.open_reservations == 1
    assert snapshot.reserved_input_tokens == 20
    assert snapshot.reserved_output_tokens == 10

    gateway.cancel(reservation)


def test_completed_or_mismatched_reservations_cannot_be_reused() -> None:
    gateway = ModelBudgetGateway(_budget())
    reservation = gateway.reserve(input_tokens=20, max_output_tokens=10)
    gateway.commit(reservation, ModelUsage(input_tokens=20, output_tokens=10, total_model_tokens=30))

    with pytest.raises(BudgetAccountingError, match="unknown"):
        gateway.commit(reservation, ModelUsage(input_tokens=1, output_tokens=1, total_model_tokens=2))
    with pytest.raises(BudgetAccountingError, match="unknown"):
        gateway.cancel(reservation)


def test_usage_rejects_incoherent_total_token_accounting() -> None:
    with pytest.raises(ValueError, match="total_model_tokens"):
        ModelUsage(input_tokens=10, output_tokens=5, total_model_tokens=14)
