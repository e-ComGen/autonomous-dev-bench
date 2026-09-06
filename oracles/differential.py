"""Differential comparisons over evaluator-owned observations."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from benchmark_core.result import OracleResult
from .base import oracle_result


def _identity(value: object) -> object:
    return value


@dataclass(frozen=True, slots=True)
class DifferentialOracle:
    oracle_id: str = "differential"
    version: str = "v1"

    def evaluate(self, baseline: object, candidate: object, *,
                 projections: Mapping[str, Callable[[object], object]] | None = None,
                 comparator: Callable[[object, object], bool] | None = None,
                 evidence_refs: Iterable[object] = ()) -> OracleResult:
        project = projections or {"observable": _identity}
        compare = comparator or (lambda left, right: left == right)
        equal: dict[str, bool] = {}
        errors: dict[str, str] = {}
        for name in sorted(project):
            try:
                projection = project[name]
                equal[name] = bool(compare(projection(baseline), projection(candidate)))
            except BaseException as exc:
                equal[name] = False
                errors[name] = f"{type(exc).__name__}: {exc}"
        passed = bool(equal) and all(equal.values())
        return oracle_result(self.oracle_id, self.version, passed,
            {"comparisons": equal, "errors": errors, "matched_count": sum(equal.values()), "total_count": len(equal)},
            evidence_refs, None if passed else "candidate differs from baseline observations")

    __call__ = evaluate
