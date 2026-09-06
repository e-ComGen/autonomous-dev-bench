"""Public-name and callable-signature compatibility oracle."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import inspect

from benchmark_core.result import OracleResult
from .base import oracle_result


def public_api_snapshot(subject: object) -> dict[str, str]:
    if isinstance(subject, Mapping):
        members = subject.items()
    else:
        names = getattr(subject, "__all__", None)
        if names is None:
            names = tuple(name for name in dir(subject) if not name.startswith("_"))
        members = ((name, getattr(subject, name)) for name in names)
    snapshot: dict[str, str] = {}
    for name, value in members:
        if str(name).startswith("_"):
            continue
        try:
            signature = str(inspect.signature(value)) if callable(value) else type(value).__qualname__
        except (TypeError, ValueError):
            signature = "callable" if callable(value) else type(value).__qualname__
        snapshot[str(name)] = signature
    return snapshot


@dataclass(frozen=True, slots=True)
class PublicApiOracle:
    oracle_id: str = "public-api"
    version: str = "v1"

    def evaluate(self, baseline: object, candidate: object, *, evidence_refs: Iterable[object] = ()) -> OracleResult:
        expected = public_api_snapshot(baseline)
        actual = public_api_snapshot(candidate)
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
        passed = not missing and not changed
        return oracle_result(self.oracle_id, self.version, passed,
            {"missing": missing, "added": added, "changed_signatures": changed,
             "expected_count": len(expected), "actual_count": len(actual)}, evidence_refs,
            None if passed else "public names or signatures changed")

    __call__ = evaluate
