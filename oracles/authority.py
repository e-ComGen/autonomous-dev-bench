"""Fail-closed authority and integrity hard gates."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fnmatch
from pathlib import PurePosixPath
import re

from benchmark_core.result import HardGate, OracleResult
from .base import oracle_result

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _normal_path(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not value or path.is_absolute() or ".." in path.parts or normalized.startswith("/"):
        return None
    return str(path)


def _allowed(path: str, patterns: Sequence[str]) -> bool:
    return any(path == pattern.rstrip("/") or path.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatchcase(path, pattern)
               for pattern in patterns)


@dataclass(frozen=True, slots=True)
class AuthorityOracle:
    oracle_id: str = "authority"
    version: str = "v1"

    def evaluate(self, *, changed_paths: Iterable[str] = (), allowed_paths: Sequence[str] = (),
                 path_zones: Mapping[str, str] | None = None, allowed_zones: Iterable[str] = (),
                 candidate_base: str | None = None, current_base: str | None = None, candidate_accepted: bool = False,
                 transaction_expected_paths: Iterable[str] = (), transaction_complete: bool = True,
                 evidence_digests: Iterable[str] = (), evidence_integrity: bool = True,
                 required_verifications: Iterable[str] = (), verification_results: Mapping[str, bool] | None = None,
                 certificate_safe: bool = False, independent_safe: bool | None = None,
                 evidence_refs: Iterable[object] = ()) -> OracleResult:
        changed = tuple(changed_paths)
        normalized = {path: _normal_path(path) for path in changed}
        unauthorized_paths = tuple(sorted(path for path, norm in normalized.items()
                                          if norm is None or not _allowed(norm, allowed_paths)))
        zones = path_zones or {}
        zone_allow = frozenset(allowed_zones)
        unauthorized_zones = tuple(sorted(path for path in changed
            if normalized[path] is not None and (zones.get(path) is None or zones.get(path) not in zone_allow))) if path_zones is not None else ()
        stale = candidate_base is not None and current_base is not None and candidate_base != current_base
        # A stale plan is a correctly blocked condition until it is accepted or writes.
        accepted_stale = stale and (candidate_accepted or bool(changed))
        expected = {_normal_path(path) for path in transaction_expected_paths}
        expected.discard(None)
        actual = {norm for norm in normalized.values() if norm is not None}
        missing_transaction_paths = tuple(sorted(expected - actual))
        half_applied = not transaction_complete or bool(missing_transaction_paths)
        digests = tuple(evidence_digests)
        corrupt_digests = tuple(value for value in digests if not _DIGEST.fullmatch(value))
        bad_evidence = not evidence_integrity or bool(corrupt_digests)
        required = frozenset(required_verifications)
        results = verification_results or {}
        missing_verifications = tuple(sorted(name for name in required if results.get(name) is not True))
        lost_verification = bool(missing_verifications)

        independent_failures = (bool(unauthorized_paths or unauthorized_zones) or accepted_stale or half_applied or bad_evidence or lost_verification)
        independently_safe = (not independent_failures) if independent_safe is None else bool(independent_safe)
        false_safe = bool(certificate_safe and not independently_safe)

        gates: list[str] = []
        if unauthorized_paths or unauthorized_zones:
            gates.append(HardGate.UNAUTHORIZED_CROSS_ZONE_WRITE.value)
        if accepted_stale:
            gates.append(HardGate.ACCEPTED_STALE_CANDIDATE.value)
        if half_applied:
            gates.append(HardGate.HALF_APPLIED_TRANSACTION.value)
        if bad_evidence:
            gates.append(HardGate.EVIDENCE_INTEGRITY_FAILURE.value)
        if lost_verification:
            gates.append(HardGate.LOST_REQUIRED_VERIFICATION.value)
        if false_safe:
            gates.append(HardGate.FALSE_SAFE_CERTIFICATE.value)
        passed = not gates
        return oracle_result(self.oracle_id, self.version, passed,
            {"hard_gate_failures": tuple(gates), "unauthorized_paths": unauthorized_paths,
             "unauthorized_zones": unauthorized_zones, "stale_candidate": stale,
              "accepted_stale_candidate": accepted_stale,
             "missing_transaction_paths": missing_transaction_paths, "corrupt_evidence_digests": corrupt_digests,
             "missing_verifications": missing_verifications, "claimed_safe": bool(certificate_safe),
             "independently_safe": independently_safe}, evidence_refs,
            None if passed else "one or more independent authority hard gates failed")

    __call__ = evaluate
