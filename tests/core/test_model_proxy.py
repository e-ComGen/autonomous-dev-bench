from __future__ import annotations

import pytest

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import BudgetExceeded, ModelBudgetGateway
from benchmark_core.model_proxy import (
    BudgetedModelProxyCore,
    ExactTokenEstimateUnavailable,
    PinnedRequestEstimator,
    ProviderUsageMissing,
    RequestBudgetEstimate,
)


MODEL = "deepseek-v4-flash"


def _budget() -> BudgetManifest:
    return BudgetManifest(
        input_token_cap=100,
        output_token_cap=100,
        total_model_token_cap=180,
        max_requests=3,
        wall_time_seconds=60,
        patch_byte_cap=1000,
    )


def _request(*, max_tokens: int = 40) -> dict[str, object]:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _core(request: dict[str, object], estimate: RequestBudgetEstimate) -> BudgetedModelProxyCore:
    digest = PinnedRequestEstimator.request_sha256(request)
    return BudgetedModelProxyCore(
        ModelBudgetGateway(_budget()),
        PinnedRequestEstimator({digest: estimate}),
        expected_model=MODEL,
    )


def test_unknown_request_fails_before_any_budget_reservation() -> None:
    request = _request()
    core = BudgetedModelProxyCore(
        ModelBudgetGateway(_budget()),
        PinnedRequestEstimator({}),
        expected_model=MODEL,
    )

    with pytest.raises(ExactTokenEstimateUnavailable):
        core.admit(request)

    assert core.gateway.snapshot().open_reservations == 0
    assert core.gateway.snapshot().requests == 0


def test_admission_requires_exact_model_and_stream_usage() -> None:
    request = _request()
    core = _core(request, RequestBudgetEstimate(20, 40, 60))

    wrong_model = dict(request, model="other")
    with pytest.raises(ValueError, match="model identity"):
        core.admit(wrong_model)

    no_stream = dict(request, stream=False)
    with pytest.raises(ValueError, match="streaming"):
        core.admit(no_stream)

    no_usage = dict(request, stream_options={})
    with pytest.raises(ValueError, match="include_usage"):
        core.admit(no_usage)


def test_terminal_provider_usage_commits_primary_and_secondary_accounting() -> None:
    request = _request()
    core = _core(request, RequestBudgetEstimate(30, 40, 90))
    admission = core.admit(request)

    core.commit_usage(
        admission,
        {
            "prompt_tokens": 30,
            "completion_tokens": 35,
            "total_tokens": 80,
            "prompt_cache_hit_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 15},
        },
        wall_time_ms=123,
        cost_usd=0.25,
    )

    snapshot = core.snapshot()
    assert not snapshot.accounting_unknown
    assert snapshot.budget.input_tokens == 30
    assert snapshot.budget.output_tokens == 35
    assert snapshot.budget.total_model_tokens == 80
    assert snapshot.budget.reasoning_tokens == 15
    assert snapshot.budget.cache_tokens == 7
    assert snapshot.budget.wall_time_ms == 123
    assert snapshot.budget.cost_usd == pytest.approx(0.25)
    assert snapshot.budget.requests == 1
    assert snapshot.budget.open_reservations == 0
    core.require_clean_accounting()


def test_openai_cached_token_spelling_is_accepted() -> None:
    request = _request()
    core = _core(request, RequestBudgetEstimate(20, 40, 60))
    admission = core.admit(request)

    core.commit_usage(
        admission,
        {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 3},
        },
    )

    snapshot = core.snapshot()
    assert snapshot.budget.total_model_tokens == 30
    assert snapshot.budget.cache_tokens == 3


def test_dispatched_request_without_terminal_usage_fails_closed_and_keeps_capacity_reserved() -> None:
    request = _request()
    core = _core(request, RequestBudgetEstimate(20, 40, 60))
    admission = core.admit(request)

    core.mark_accounting_unknown(admission)

    snapshot = core.snapshot()
    assert snapshot.accounting_unknown
    assert snapshot.unknown_request_sha256 == (admission.request_sha256,)
    assert snapshot.budget.open_reservations == 1
    assert snapshot.budget.reserved_total_tokens == 60
    with pytest.raises(ProviderUsageMissing):
        core.require_clean_accounting()


def test_cancel_before_dispatch_refunds_reservation_without_charging_request() -> None:
    request = _request()
    core = _core(request, RequestBudgetEstimate(20, 40, 60))
    admission = core.admit(request)

    core.cancel_before_dispatch(admission)

    snapshot = core.snapshot()
    assert snapshot.budget.open_reservations == 0
    assert snapshot.budget.requests == 0
    core.require_clean_accounting()


def test_proxy_reservation_enforces_global_budget_before_dispatch() -> None:
    first_request = _request(max_tokens=40)
    second_request = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "second"}],
        "max_tokens": 40,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    estimates = {
        PinnedRequestEstimator.request_sha256(first_request): RequestBudgetEstimate(50, 40, 90),
        PinnedRequestEstimator.request_sha256(second_request): RequestBudgetEstimate(50, 40, 90),
    }
    core = BudgetedModelProxyCore(
        ModelBudgetGateway(_budget()),
        PinnedRequestEstimator(estimates),
        expected_model=MODEL,
    )

    core.admit(first_request)
    with pytest.raises(BudgetExceeded, match="total_model_token_cap"):
        core.admit(second_request)
