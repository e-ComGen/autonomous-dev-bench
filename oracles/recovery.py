"""Crash/restart recovery invariant oracle."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from benchmark_core.result import OracleResult
from .base import oracle_result


@dataclass(frozen=True, slots=True)
class RecoveryOracle:
    oracle_id: str = "recovery"
    version: str = "v1"

    def evaluate(self, expected_state: Mapping[str, object], recovered_state: Mapping[str, object], *,
                 duplicate_side_effects: int = 0, pending_transactions: int = 0,
                 evidence_refs: Iterable[object] = ()) -> OracleResult:
        missing = tuple(sorted(set(expected_state) - set(recovered_state)))
        changed = tuple(sorted(key for key in expected_state.keys() & recovered_state.keys()
                               if expected_state[key] != recovered_state[key]))
        passed = not missing and not changed and duplicate_side_effects == 0 and pending_transactions == 0
        return oracle_result(self.oracle_id, self.version, passed,
            {"missing_state": missing, "changed_state": changed, "duplicate_side_effects": duplicate_side_effects,
             "pending_transactions": pending_transactions}, evidence_refs,
            None if passed else "recovery invariants failed")

    __call__ = evaluate
