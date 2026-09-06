"""Versioned task specifications and leakage-safe audience projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .identity import CanonicalModel, FrozenDict, VersionIdentity, freeze_json, require_identifier, require_nonempty, require_unique


def _ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        require_identifier(value, name)
    return require_unique(result, name)


@dataclass(frozen=True, slots=True)
class ExpectedScope(CanonicalModel):
    affected_domains: tuple[str, ...]
    candidate_zones: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "affected_domains", _ids(self.affected_domains, "affected_domains"))
        object.__setattr__(self, "candidate_zones", _ids(self.candidate_zones, "candidate_zones"))


@dataclass(frozen=True, slots=True)
class CrossZoneContract(CanonicalModel):
    contract_id: str
    producer_zone: str
    consumer_zone: str

    def __post_init__(self) -> None:
        for name in ("contract_id", "producer_zone", "consumer_zone"):
            require_identifier(getattr(self, name), name)
        if self.producer_zone == self.consumer_zone:
            raise ValueError("a cross-zone contract must connect different zones")


@dataclass(frozen=True, slots=True)
class FunctionalOracleRef(CanonicalModel):
    oracle_id: str
    version: str

    def __post_init__(self) -> None:
        require_identifier(self.oracle_id, "oracle_id")
        require_identifier(self.version, "version")


@dataclass(frozen=True, slots=True)
class ArchitectureConstraints(CanonicalModel):
    acceptable_families: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "acceptable_families", _ids(self.acceptable_families, "acceptable_families"))
        object.__setattr__(self, "forbidden", _ids(self.forbidden, "forbidden"))
        overlap = set(self.acceptable_families) & set(self.forbidden)
        if overlap:
            raise ValueError(f"architecture families cannot be both acceptable and forbidden: {sorted(overlap)!r}")


@dataclass(frozen=True, slots=True)
class TaskOwnerView(CanonicalModel):
    user_request: str


@dataclass(frozen=True, slots=True)
class AutoZoningView(CanonicalModel):
    user_request: str
    source_snapshot: object

    def __post_init__(self) -> None:
        snapshot = self.source_snapshot
        if not isinstance(snapshot, Mapping):
            raise ValueError("source_snapshot must be a mapping")
        fingerprint = snapshot.get("input_fingerprint")
        if (
            not isinstance(fingerprint, str) or len(fingerprint) != 71
            or not fingerprint.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in fingerprint[7:])
        ):
            raise ValueError("source_snapshot.input_fingerprint must be sha256:<64 lowercase hex>")
        paths = snapshot.get("scope_paths")
        if not isinstance(paths, (tuple, list)):
            raise ValueError("source_snapshot.scope_paths must be a list or tuple")
        normalized: list[str] = []
        for path in paths:
            parts = path.replace("\\", "/").split("/") if isinstance(path, str) else []
            if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or (parts and ":" in parts[0]) or ".." in parts:
                raise ValueError("source_snapshot.scope_paths must contain repository-relative paths")
            normalized.append(path.replace("\\", "/"))
        require_unique(tuple(normalized), "source_snapshot.scope_paths")
        object.__setattr__(self, "source_snapshot", freeze_json({**snapshot, "scope_paths": normalized}))


@dataclass(frozen=True, slots=True)
class ArchitectureAssuranceView(CanonicalModel):
    source_snapshot: object
    zoning_proposal: object
    architecture_proposal: object

    def __post_init__(self) -> None:
        for name in ("source_snapshot", "zoning_proposal", "architecture_proposal"):
            object.__setattr__(self, name, freeze_json(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class CoderView(CanonicalModel):
    user_request: str
    approved_zones: tuple[str, ...]
    approved_contracts: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "approved_zones", _ids(self.approved_zones, "approved_zones"))
        object.__setattr__(self, "approved_contracts", _ids(self.approved_contracts, "approved_contracts"))


@dataclass(frozen=True, slots=True)
class AutoRefactoringView(CanonicalModel):
    candidate_snapshot: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_snapshot", freeze_json(self.candidate_snapshot))


@dataclass(frozen=True, slots=True)
class OracleView(CanonicalModel):
    """Private evaluator projection; this is the only view carrying expectations."""

    task: "TaskSpec"


class TaskAudience(str, Enum):
    TASK_OWNER = "task_owner"
    AUTO_ZONING = "auto_zoning"
    ARCHITECTURE_ASSURANCE = "architecture_assurance"
    CODER = "coder"
    AUTO_REFACTORING = "auto_refactoring"
    ORACLE = "oracle"


@dataclass(frozen=True, slots=True)
class TaskSpec(CanonicalModel):
    """Private source of truth for a task.

    Never pass this object to the system under test.  Use :meth:`project` to
    construct a capability-local view that omits oracle and expected-scope data.
    """

    task_id: str
    spec_version: str
    project_id: str
    baseline_checkpoint: str
    user_request: str
    expected_scope: ExpectedScope
    cross_zone_contracts: tuple[CrossZoneContract, ...]
    functional_oracle_ref: FunctionalOracleRef
    architecture_constraints: ArchitectureConstraints

    def __post_init__(self) -> None:
        for name in ("task_id", "spec_version", "project_id", "baseline_checkpoint"):
            require_identifier(getattr(self, name), name)
        require_nonempty(self.user_request, "user_request")
        contracts = tuple(self.cross_zone_contracts)
        require_unique(tuple(c.contract_id for c in contracts), "cross_zone_contracts")
        object.__setattr__(self, "cross_zone_contracts", contracts)

    @property
    def identity(self) -> VersionIdentity:
        return VersionIdentity(self.task_id, self.spec_version, self.content_digest)

    def project(self, audience: TaskAudience | str, **context: Any) -> CanonicalModel:
        """Build an explicit least-information view for one benchmark stage."""

        try:
            audience = TaskAudience(audience)
        except ValueError as exc:
            raise ValueError(f"unsupported task audience: {audience!r}") from exc
        if audience is TaskAudience.TASK_OWNER:
            return TaskOwnerView(self.user_request)
        if audience is TaskAudience.AUTO_ZONING:
            return AutoZoningView(self.user_request, _required(context, "source_snapshot"))
        if audience is TaskAudience.ARCHITECTURE_ASSURANCE:
            return ArchitectureAssuranceView(
                _required(context, "source_snapshot"),
                _required(context, "zoning_proposal"),
                _required(context, "architecture_proposal"),
            )
        if audience is TaskAudience.CODER:
            return CoderView(
                self.user_request,
                tuple(_required(context, "approved_zones")),
                tuple(_required(context, "approved_contracts")),
            )
        if audience is TaskAudience.AUTO_REFACTORING:
            return AutoRefactoringView(_required(context, "candidate_snapshot"))
        return OracleView(self)


def _required(context: Mapping[str, Any], name: str) -> Any:
    if name not in context:
        raise ValueError(f"projection requires {name}")
    return context[name]
