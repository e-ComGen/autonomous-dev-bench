"""Shared model-budget authority for causal A/B coding experiments.

Both stock and orchestrated arms must consume model calls through the same
reservation/accounting contract. The gateway owns fairness enforcement; agent
implementations only report predicted call ceilings and observed usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Final
from uuid import uuid4

from .experiment_manifest import BudgetManifest


class BudgetExceeded(RuntimeError):
    """Raised before dispatch when a requested model call cannot fit the budget."""


class BudgetAccountingError(RuntimeError):
    """Raised when observed provider usage cannot be reconciled with a reservation."""


@dataclass(frozen=True, slots=True)
class ModelCallReservation:
    reservation_id: str
    reserved_input_tokens: int
    reserved_output_tokens: int

    @property
    def reserved_total_tokens(self) -> int:
        return self.reserved_input_tokens + self.reserved_output_tokens


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    total_model_tokens: int
    reasoning_tokens: int = 0
    cache_tokens: int = 0
    cost_usd: float = 0.0
    wall_time_ms: int = 0

    def __post_init__(self) -> None:
        for name in (
            "input_tokens",
            "output_tokens",
            "total_model_tokens",
            "reasoning_tokens",
            "cache_tokens",
            "wall_time_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.total_model_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total_model_tokens cannot be smaller than input_tokens + output_tokens")
        if isinstance(self.cost_usd, bool) or not isinstance(self.cost_usd, (int, float)) or self.cost_usd < 0:
            raise ValueError("cost_usd must be a non-negative number")


@dataclass(frozen=True, slots=True)
class ModelBudgetSnapshot:
    input_tokens: int
    output_tokens: int
    total_model_tokens: int
    reasoning_tokens: int
    cache_tokens: int
    cost_usd: float
    wall_time_ms: int
    requests: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    open_reservations: int


@dataclass(slots=True)
class _ReservationState:
    reservation: ModelCallReservation


class ModelBudgetGateway:
    """Thread-safe hard budget authority shared by all model-calling arms.

    A call reserves its worst-case input/output token envelope before dispatch.
    Completing the call replaces that reservation with actual provider usage,
    refunding unused capacity. ``total_model_tokens`` is the primary fairness
    counter; the remaining counters are retained for audit and secondary
    analysis.
    """

    _ID_PREFIX: Final[str] = "model-call-"

    def __init__(self, budget: BudgetManifest):
        self._budget = budget
        self._lock = RLock()
        self._reservations: dict[str, _ReservationState] = {}
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_model_tokens = 0
        self._reasoning_tokens = 0
        self._cache_tokens = 0
        self._cost_usd = 0.0
        self._wall_time_ms = 0
        self._requests = 0

    @property
    def budget(self) -> BudgetManifest:
        return self._budget

    def reserve(self, *, input_tokens: int, max_output_tokens: int) -> ModelCallReservation:
        input_tokens = self._non_negative(input_tokens, "input_tokens")
        max_output_tokens = self._non_negative(max_output_tokens, "max_output_tokens")
        if input_tokens == 0 and max_output_tokens == 0:
            raise ValueError("a model call reservation cannot reserve zero tokens")

        with self._lock:
            if self._requests + len(self._reservations) >= self._budget.max_requests:
                raise BudgetExceeded("max_requests exhausted")

            reserved_input, reserved_output = self._reserved_tokens_unlocked()
            projected_input = self._input_tokens + reserved_input + input_tokens
            projected_output = self._output_tokens + reserved_output + max_output_tokens
            projected_total = self._total_model_tokens + reserved_input + reserved_output + input_tokens + max_output_tokens

            if projected_input > self._budget.input_token_cap:
                raise BudgetExceeded("input_token_cap exceeded")
            if projected_output > self._budget.output_token_cap:
                raise BudgetExceeded("output_token_cap exceeded")
            if projected_total > self._budget.total_model_token_cap:
                raise BudgetExceeded("total_model_token_cap exceeded")

            reservation = ModelCallReservation(
                reservation_id=self._ID_PREFIX + uuid4().hex,
                reserved_input_tokens=input_tokens,
                reserved_output_tokens=max_output_tokens,
            )
            self._reservations[reservation.reservation_id] = _ReservationState(reservation=reservation)
            return reservation

    def commit(self, reservation: ModelCallReservation, usage: ModelUsage) -> ModelBudgetSnapshot:
        with self._lock:
            state = self._pop_reservation_unlocked(reservation)
            reserved = state.reservation
            if usage.input_tokens > reserved.reserved_input_tokens:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("observed input tokens exceed reserved input tokens")
            if usage.output_tokens > reserved.reserved_output_tokens:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("observed output tokens exceed reserved output tokens")
            if usage.total_model_tokens > reserved.reserved_total_tokens:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("observed total model tokens exceed reserved token envelope")

            projected_input = self._input_tokens + usage.input_tokens
            projected_output = self._output_tokens + usage.output_tokens
            projected_total = self._total_model_tokens + usage.total_model_tokens
            if projected_input > self._budget.input_token_cap:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("committed input usage exceeds input_token_cap")
            if projected_output > self._budget.output_token_cap:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("committed output usage exceeds output_token_cap")
            if projected_total > self._budget.total_model_token_cap:
                self._reservations[reserved.reservation_id] = state
                raise BudgetAccountingError("committed total usage exceeds total_model_token_cap")

            self._input_tokens = projected_input
            self._output_tokens = projected_output
            self._total_model_tokens = projected_total
            self._reasoning_tokens += usage.reasoning_tokens
            self._cache_tokens += usage.cache_tokens
            self._cost_usd += float(usage.cost_usd)
            self._wall_time_ms += usage.wall_time_ms
            self._requests += 1
            return self._snapshot_unlocked()

    def cancel(self, reservation: ModelCallReservation) -> ModelBudgetSnapshot:
        """Release an undispatched/failed-before-accounting reservation without charging a request."""
        with self._lock:
            self._pop_reservation_unlocked(reservation)
            return self._snapshot_unlocked()

    def snapshot(self) -> ModelBudgetSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    @staticmethod
    def _non_negative(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value

    def _pop_reservation_unlocked(self, reservation: ModelCallReservation) -> _ReservationState:
        state = self._reservations.get(reservation.reservation_id)
        if state is None or state.reservation != reservation:
            raise BudgetAccountingError("unknown, already completed, or mismatched reservation")
        del self._reservations[reservation.reservation_id]
        return state

    def _reserved_tokens_unlocked(self) -> tuple[int, int]:
        input_tokens = sum(state.reservation.reserved_input_tokens for state in self._reservations.values())
        output_tokens = sum(state.reservation.reserved_output_tokens for state in self._reservations.values())
        return input_tokens, output_tokens

    def _snapshot_unlocked(self) -> ModelBudgetSnapshot:
        reserved_input, reserved_output = self._reserved_tokens_unlocked()
        return ModelBudgetSnapshot(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_model_tokens=self._total_model_tokens,
            reasoning_tokens=self._reasoning_tokens,
            cache_tokens=self._cache_tokens,
            cost_usd=self._cost_usd,
            wall_time_ms=self._wall_time_ms,
            requests=self._requests,
            reserved_input_tokens=reserved_input,
            reserved_output_tokens=reserved_output,
            open_reservations=len(self._reservations),
        )
