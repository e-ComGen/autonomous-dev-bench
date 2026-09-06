"""Common helpers for independent, reusable oracles."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from benchmark_core.result import OracleResult, RunStatus


def oracle_result(oracle_id: str, version: str, passed: bool, measurements: Mapping[str, object],
                  evidence_refs: Iterable[object] = (), message: str | None = None) -> OracleResult:
    return OracleResult(oracle_id, version, RunStatus.PASS if passed else RunStatus.FAIL,
                        measurements, tuple(evidence_refs), message)
