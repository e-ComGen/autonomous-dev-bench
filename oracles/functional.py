"""Independent functional property execution."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from benchmark_core.result import OracleResult
from .base import oracle_result


@dataclass(frozen=True, slots=True)
class FunctionalOracle:
    oracle_id: str = "functional"
    version: str = "v1"

    def evaluate(self, checks: Mapping[str, Callable[[], object] | bool], *, evidence_refs: Iterable[object] = ()) -> OracleResult:
        outcomes: dict[str, bool] = {}
        errors: dict[str, str] = {}
        for name in sorted(checks):
            try:
                check = checks[name]
                outcomes[name] = bool(check() if callable(check) else check)
            except BaseException as exc:
                outcomes[name] = False
                errors[name] = f"{type(exc).__name__}: {exc}"
        passed = bool(outcomes) and all(outcomes.values())
        return oracle_result(self.oracle_id, self.version, passed,
            {"checks": outcomes, "errors": errors, "passed_count": sum(outcomes.values()), "total_count": len(outcomes)},
            evidence_refs, None if passed else "one or more independent functional checks failed")

    __call__ = evaluate
