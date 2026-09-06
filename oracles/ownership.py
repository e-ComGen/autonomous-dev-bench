"""Ownership comparison against evaluator-held labels."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from benchmark_core.result import OracleResult
from .base import oracle_result


@dataclass(frozen=True, slots=True)
class OwnershipOracle:
    oracle_id: str = "ownership"
    version: str = "v1"

    def evaluate(self, expected: Mapping[str, str], actual: Mapping[str, str | None], *,
                 evidence_refs: Iterable[object] = ()) -> OracleResult:
        keys = sorted(expected)
        correct = tuple(key for key in keys if actual.get(key) == expected[key])
        wrong = tuple(key for key in keys if key in actual and actual[key] is not None and actual[key] != expected[key])
        unknown = tuple(key for key in keys if key not in actual or actual[key] is None)
        extra = tuple(sorted(set(actual) - set(expected)))
        total = len(keys)
        accuracy = len(correct) / total if total else 1.0
        coverage = (total - len(unknown)) / total if total else 1.0
        passed = not wrong and not unknown
        return oracle_result(self.oracle_id, self.version, passed,
            {"correct": len(correct), "incorrect": len(wrong), "unknown": len(unknown), "extra": len(extra),
             "accuracy": accuracy, "coverage": coverage, "incorrect_items": wrong, "unknown_items": unknown,
             "extra_items": extra}, evidence_refs, None if passed else "ownership labels differ or are incomplete")

    __call__ = evaluate
