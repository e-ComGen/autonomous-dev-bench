"""Budgeted OpenAI-compatible model transport for causal A/B experiments.

The proxy is deliberately stricter than an ordinary reverse proxy: every model
request must receive an exact pre-dispatch token envelope, and every dispatched
request must finish with provider usage that can be reconciled with the shared
:class:`ModelBudgetGateway`. Unknown accounting is a trial-invalidating state,
never an excuse to under-count model use.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Mapping, Protocol, runtime_checkable

from .model_budget import ModelBudgetGateway, ModelCallReservation, ModelUsage


class ExactTokenEstimateUnavailable(RuntimeError):
    """Raised before provider dispatch when exact request pricing is unavailable."""


class ProviderUsageMissing(RuntimeError):
    """Raised when a dispatched provider request cannot be reconciled exactly."""


@dataclass(frozen=True, slots=True)
class RequestBudgetEstimate:
    """Exact/worst-case token envelope for one wire request before dispatch."""

    input_tokens: int
    max_output_tokens: int
    max_total_tokens: int

    def __post_init__(self) -> None:
        for name in ("input_tokens", "max_output_tokens", "max_total_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_total_tokens < self.input_tokens + self.max_output_tokens:
            raise ValueError("max_total_tokens cannot be smaller than input_tokens + max_output_tokens")


@runtime_checkable
class ExactRequestBudgetEstimator(Protocol):
    """Trusted admission component that prices the exact provider wire request."""

    def estimate(self, request: Mapping[str, object]) -> RequestBudgetEstimate:
        """Return an exact/worst-case envelope or raise before dispatch."""


@dataclass(frozen=True, slots=True)
class ProxyAdmission:
    request_sha256: str
    reservation: ModelCallReservation


@dataclass(frozen=True, slots=True)
class BudgetProxySnapshot:
    accounting_unknown: bool
    unknown_request_sha256: tuple[str, ...]
    budget: object


class PinnedRequestEstimator:
    """Exact estimator for deterministic qualification fixtures.

    Production paid execution must replace this with an exact tokenizer-aware
    estimator. Unknown request bytes fail closed; there is no character/token
    heuristic fallback.
    """

    def __init__(self, estimates: Mapping[str, RequestBudgetEstimate]):
        self._estimates = dict(estimates)

    @staticmethod
    def request_sha256(request: Mapping[str, object]) -> str:
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(encoded).hexdigest()

    def estimate(self, request: Mapping[str, object]) -> RequestBudgetEstimate:
        digest = self.request_sha256(request)
        try:
            return self._estimates[digest]
        except KeyError as error:
            raise ExactTokenEstimateUnavailable(f"no exact token estimate for request {digest}") from error


class BudgetedModelProxyCore:
    """Admission/accounting state shared by the HTTP proxy boundary."""

    def __init__(
        self,
        gateway: ModelBudgetGateway,
        estimator: ExactRequestBudgetEstimator,
        *,
        expected_model: str,
    ) -> None:
        if not expected_model.strip():
            raise ValueError("expected_model must be non-empty")
        self._gateway = gateway
        self._estimator = estimator
        self._expected_model = expected_model
        self._lock = RLock()
        self._unknown: list[str] = []

    @property
    def gateway(self) -> ModelBudgetGateway:
        return self._gateway

    def admit(self, request: Mapping[str, object]) -> ProxyAdmission:
        """Validate and reserve a call before any upstream network dispatch."""
        if request.get("model") != self._expected_model:
            raise ValueError("model identity differs from the experiment model")
        if request.get("stream") is not True:
            raise ValueError("budget proxy requires streaming provider usage")
        stream_options = request.get("stream_options")
        if not isinstance(stream_options, Mapping) or stream_options.get("include_usage") is not True:
            raise ValueError("budget proxy requires stream_options.include_usage=true")

        estimate = self._estimator.estimate(request)
        reservation = self._gateway.reserve(
            input_tokens=estimate.input_tokens,
            max_output_tokens=estimate.max_output_tokens,
            max_total_tokens=estimate.max_total_tokens,
        )
        return ProxyAdmission(
            request_sha256=PinnedRequestEstimator.request_sha256(request),
            reservation=reservation,
        )

    def commit_usage(
        self,
        admission: ProxyAdmission,
        usage: Mapping[str, object],
        *,
        wall_time_ms: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Commit the provider's terminal DeepSeek/OpenAI-compatible usage object."""
        prompt_tokens = self._required_int(usage, "prompt_tokens")
        completion_tokens = self._required_int(usage, "completion_tokens")
        total_raw = usage.get("total_tokens")
        if total_raw is None:
            total_tokens = prompt_tokens + completion_tokens
        else:
            total_tokens = self._int_value(total_raw, "total_tokens")

        cache_tokens = 0
        cache_raw = usage.get("prompt_cache_hit_tokens")
        if cache_raw is not None:
            cache_tokens = self._int_value(cache_raw, "prompt_cache_hit_tokens")
        details = usage.get("prompt_tokens_details")
        if cache_tokens == 0 and isinstance(details, Mapping) and details.get("cached_tokens") is not None:
            cache_tokens = self._int_value(details["cached_tokens"], "cached_tokens")

        reasoning_tokens = 0
        completion_details = usage.get("completion_tokens_details")
        if isinstance(completion_details, Mapping) and completion_details.get("reasoning_tokens") is not None:
            reasoning_tokens = self._int_value(completion_details["reasoning_tokens"], "reasoning_tokens")

        self._gateway.commit(
            admission.reservation,
            ModelUsage(
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                total_model_tokens=total_tokens,
                reasoning_tokens=reasoning_tokens,
                cache_tokens=cache_tokens,
                cost_usd=cost_usd,
                wall_time_ms=wall_time_ms,
            ),
        )

    def cancel_before_dispatch(self, admission: ProxyAdmission) -> None:
        """Release a reservation only when the request is known not to have left the proxy."""
        self._gateway.cancel(admission.reservation)

    def mark_accounting_unknown(self, admission: ProxyAdmission) -> None:
        """Fail closed after dispatch when terminal provider usage is unavailable.

        The reservation intentionally remains open, preventing the missing
        usage from being silently refunded/reused.
        """
        with self._lock:
            if admission.request_sha256 not in self._unknown:
                self._unknown.append(admission.request_sha256)

    def require_clean_accounting(self) -> None:
        snapshot = self.snapshot()
        if snapshot.accounting_unknown or snapshot.budget.open_reservations:
            raise ProviderUsageMissing(
                "model transport has dispatched request(s) without exact terminal usage"
            )

    def snapshot(self) -> BudgetProxySnapshot:
        with self._lock:
            unknown = tuple(self._unknown)
        return BudgetProxySnapshot(
            accounting_unknown=bool(unknown),
            unknown_request_sha256=unknown,
            budget=self._gateway.snapshot(),
        )

    @classmethod
    def _required_int(cls, source: Mapping[str, object], name: str) -> int:
        if name not in source:
            raise ProviderUsageMissing(f"provider usage missing {name}")
        return cls._int_value(source[name], name)

    @staticmethod
    def _int_value(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProviderUsageMissing(f"provider usage has invalid {name}")
        return value
