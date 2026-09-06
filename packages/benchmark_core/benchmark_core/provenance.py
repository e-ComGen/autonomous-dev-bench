"""Neutral, canonical run provenance records."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import platform
from typing import Mapping

from .identity import Sha256Digest, canonical_json


@dataclass(frozen=True)
class Provenance:
    benchmark_spec_version: str
    benchmark_core_version: str
    corpus_version: str
    runner_host_fingerprint: str
    started_at: str
    completed_at: str | None = None
    component_versions: tuple[tuple[str, str], ...] = ()
    policy_versions: tuple[tuple[str, str], ...] = ()
    evidence_root_digest: str | None = None

    @property
    def digest(self) -> str: return str(Sha256Digest.of(self))

    def to_dict(self) -> dict[str, object]: return asdict(self)

    @classmethod
    def started(cls, *, benchmark_spec_version: str, benchmark_core_version: str,
                corpus_version: str, component_versions: Mapping[str, str] | None = None,
                policy_versions: Mapping[str, str] | None = None) -> "Provenance":
        host = str(Sha256Digest.of({"system": platform.system(), "release": platform.release(),
                                   "machine": platform.machine(), "python": platform.python_version()}))
        return cls(benchmark_spec_version, benchmark_core_version, corpus_version, host,
                   datetime.now(timezone.utc).isoformat(),
                   component_versions=tuple(sorted((component_versions or {}).items())),
                   policy_versions=tuple(sorted((policy_versions or {}).items())))
