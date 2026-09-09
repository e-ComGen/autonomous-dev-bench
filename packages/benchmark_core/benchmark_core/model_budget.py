"""Shared model-budget authority for paired coding experiments.

The same gateway is intended to sit in front of every model call for every arm.
It owns admission/accounting only; it does not own agent orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import time

from .experiment_manifest import BudgetManifest


def _non_negative(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Provider-reported usage for one completed model request.

    ``reasoning_tokens`` and ``cache_tokens`` are diagnostic dimensions and are
    not added again to ``total_model_tokens`` because providers commonly report
    them as subsets of completion/input usage respectively.
    """

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cache_tokens: int = 0
    cost_usd_micros: int = 0

    def __post_init__(self) -> None:
        for field in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_tokens",
            "cost_usd_micros",
        ):
            _non_negative(getattr(self, field), field)

    @property
    def total_model_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ModelBudgetTicket:
    request_index: int
    reserved_output_tokens: int


@dataclass(frozen=True, slots=True)
class ModelBudgetSnapshot:
    requests: int
    input_tokens: int
    output_tokens: int
    total_model_tokens: int
    reasoning_tokens: int
    cache_tokens: int
    cost_usd_micros: int
    reserved_output_tokens: int
    elapsed_seconds: float
    violations: tuple[str, ...]
    accounting_valid: bool

    @property
    def exhausted(self) -> bool:
        return bool(self.violations) or not self.accounting_valid

    def as_dict(self) -> dict[str, object]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_model_tokens": self.total_model_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_tokens": self.cache_tokens,
            "cost_usd_micros": self.cost_usd_micros,
            "reserved_output_tokens": self.reserved_output_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "violations": list(self.violations),
            "accounting_valid": self.accounting_valid,
            "exhausted": self.exhausted,
        }


class ModelBudgetExceeded(RuntimeError):
    def __init__(self, snapshot: ModelBudgetSnapshot):
        self.snapshot = snapshot
        detail = ", ".join(snapshot.violations) or "model budget exhausted"
        super().__init__(detail)


class ModelAccountingError(RuntimeError):
    pass


class ModelBudgetGateway:
    """Thread-safe shared ledger and request admission authority.

    Request count and output reservations are charged at admission. Provider
    usage is charged at settlement. If a provider response crosses a hard cap,
    the usage is still recorded and the trial becomes budget-exceeded rather
    than silently hiding consumed tokens.
    """

    def __init__(self, budget: BudgetManifest, *, clock=time.monotonic):
        self.budget = budget
        self._clock = clock
        self._started = clock()
        self._lock = RLock()
        self._requests = 0
        self._input = 0
        self._output = 0
        self._reasoning = 0
        self._cache = 0
        self._cost_micros = 0
        self._reserved_output = 0
        self._active: dict[int, int] = {}
        self._accounting_valid = True

    def admit_request(self, requested_output_tokens: int | None = None) -> ModelBudgetTicket:
        """Admit one provider request and reserve its maximum useful output.

        When the caller omits a provider max-output value, the gateway reserves
        the entire remaining output allowance. This is conservative and keeps
        concurrent role calls from collectively reserving more than the arm's
        shared budget.
        """

        if requested_output_tokens is not None:
            _non_negative(requested_output_tokens, "requested_output_tokens")

        with self._lock:
            self._raise_if_unusable_locked()
            if self._requests >= self.budget.max_requests:
                raise ModelBudgetExceeded(self._snapshot_locked(extra=("max_requests",)))

            remaining_output = self.budget.output_token_cap - self._output - self._reserved_output
            remaining_total = self.budget.total_model_token_cap - self._input - self._output - self._reserved_output
            available = max(0, min(remaining_output, remaining_total))
            if available <= 0:
                raise ModelBudgetExceeded(self._snapshot_locked(extra=("token_budget",)))

            requested = available if requested_output_tokens is None else requested_output_tokens
            reservation = min(requested, available)
            if requested > 0 and reservation <= 0:
                raise ModelBudgetExceeded(self._snapshot_locked(extra=("output_token_cap",)))

            self._requests += 1
            index = self._requests
            self._reserved_output += reservation
            self._active[index] = reservation
            return ModelBudgetTicket(request_index=index, reserved_output_tokens=reservation)

    def settle(self, ticket: ModelBudgetTicket, usage: ModelUsage) -> ModelBudgetSnapshot:
        with self._lock:
            reservation = self._active.pop(ticket.request_index, None)
            if reservation is None or reservation != ticket.reserved_output_tokens:
                self._accounting_valid = False
                raise ModelAccountingError("unknown or already-settled model budget ticket")
            self._reserved_output -= reservation
            self._input += usage.input_tokens
            self._output += usage.output_tokens
            self._reasoning += usage.reasoning_tokens
            self._cache += usage.cache_tokens
            self._cost_micros += usage.cost_usd_micros
            snapshot = self._snapshot_locked()
            if snapshot.violations:
                raise ModelBudgetExceeded(snapshot)
            return snapshot

    def cancel(self, ticket: ModelBudgetTicket) -> ModelBudgetSnapshot:
        """Release an output reservation after a request failed before usage existed.

        The request itself remains charged to ``max_requests`` because the model
        route was attempted.
        """

        with self._lock:
            reservation = self._active.pop(ticket.request_index, None)
            if reservation is None or reservation != ticket.reserved_output_tokens:
                self._accounting_valid = False
                raise ModelAccountingError("unknown or already-settled model budget ticket")
            self._reserved_output -= reservation
            return self._snapshot_locked()

    def invalidate_accounting(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("accounting invalidation requires a reason")
        with self._lock:
            self._accounting_valid = False

    def snapshot(self) -> ModelBudgetSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _raise_if_unusable_locked(self) -> None:
        snapshot = self._snapshot_locked()
        if not snapshot.accounting_valid:
            raise ModelAccountingError("model accounting is invalid")
        if snapshot.violations:
            raise ModelBudgetExceeded(snapshot)

    def _violations_locked(self) -> tuple[str, ...]:
        violations: list[str] = []
        if self._input > self.budget.input_token_cap:
            violations.append("input_token_cap")
        if self._output > self.budget.output_token_cap:
            violations.append("output_token_cap")
        if self._input + self._output > self.budget.total_model_token_cap:
            violations.append("total_model_token_cap")
        if self._requests > self.budget.max_requests:
            violations.append("max_requests")
        if self._clock() - self._started > self.budget.wall_time_seconds:
            violations.append("wall_time_seconds")
        return tuple(violations)

    def _snapshot_locked(self, *, extra: tuple[str, ...] = ()) -> ModelBudgetSnapshot:
        violations = tuple(dict.fromkeys((*self._violations_locked(), *extra)))
        return ModelBudgetSnapshot(
            requests=self._requests,
            input_tokens=self._input,
            output_tokens=self._output,
            total_model_tokens=self._input + self._output,
            reasoning_tokens=self._reasoning,
            cache_tokens=self._cache,
            cost_usd_micros=self._cost_micros,
            reserved_output_tokens=self._reserved_output,
            elapsed_seconds=max(0.0, self._clock() - self._started),
            violations=violations,
            accounting_valid=self._accounting_valid,
        )
