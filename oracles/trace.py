"""Event/state-transition trace comparison."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from benchmark_core.result import OracleResult
from .base import oracle_result


@dataclass(frozen=True, slots=True)
class TraceOracle:
    oracle_id: str = "trace"
    version: str = "v1"

    def evaluate(self, expected: Sequence[object], actual: Sequence[object], *,
                 normalizer: Callable[[object], object] | None = None,
                 evidence_refs: Iterable[object] = ()) -> OracleResult:
        normalize = normalizer or (lambda value: value)
        left = tuple(normalize(event) for event in expected)
        right = tuple(normalize(event) for event in actual)
        mismatch = next((i for i in range(min(len(left), len(right))) if left[i] != right[i]), None)
        if mismatch is None and len(left) != len(right):
            mismatch = min(len(left), len(right))
        passed = left == right
        duplicates = sum(1 for index in range(1, len(right)) if right[index] == right[index - 1])
        return oracle_result(self.oracle_id, self.version, passed,
            {"expected_events": len(left), "actual_events": len(right), "first_mismatch": mismatch,
             "adjacent_duplicate_events": duplicates}, evidence_refs,
            None if passed else "event trace differs")

    __call__ = evaluate
