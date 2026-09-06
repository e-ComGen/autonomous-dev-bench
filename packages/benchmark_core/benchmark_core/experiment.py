"""Immutable experiment plans binding inputs, systems, suites and repetitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .identity import CanonicalModel, CommitPin, FrozenDict, Sha256Digest, VersionIdentity, freeze_json, require_identifier, require_unique
from .scenario import ExecutionMode


class EvaluationLevel(str, Enum):
    L0_STATIC_COMPONENT = "L0"
    L1_DETERMINISTIC_SUBSYSTEM = "L1"
    L2_LLM_ASSISTED_SUBSYSTEM = "L2"
    L3_MULTI_AGENT_PIPELINE = "L3"
    L4_END_TO_END = "L4"


class ExecutionComposition(str, Enum):
    COMPONENT = "component"
    SUBSYSTEM = "subsystem"
    PIPELINE = "pipeline"
    FULL_SYSTEM = "full_system"


@dataclass(frozen=True, slots=True)
class SystemUnderTest(CanonicalModel):
    system_id: str
    version: str
    commit_sha: CommitPin | str
    configuration: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.system_id, "system_id")
        require_identifier(self.version, "system version")
        object.__setattr__(self, "commit_sha", self.commit_sha if isinstance(self.commit_sha, CommitPin) else CommitPin(self.commit_sha))
        object.__setattr__(self, "configuration", freeze_json(self.configuration))

    @property
    def identity(self) -> VersionIdentity:
        return VersionIdentity(self.system_id, self.version, self.content_digest)


@dataclass(frozen=True, slots=True)
class SuitePlan(CanonicalModel):
    suite_id: str
    suite_version: str
    input_checkpoint: str
    adapter_id: str
    oracle_ids: tuple[str, ...]
    required_observations: tuple[str, ...]
    hard_gate_ids: tuple[str, ...]
    adapter_version: str = "1"
    policy_version: str = "1"
    acceptance_version: str = "1"
    global_hard_gate_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()
    labels_ref: str = "none"

    def __post_init__(self) -> None:
        for name in ("suite_id", "suite_version", "input_checkpoint", "adapter_id", "adapter_version", "policy_version", "acceptance_version", "labels_ref"):
            require_identifier(getattr(self, name), name)
        for name in ("oracle_ids", "required_observations", "hard_gate_ids", "global_hard_gate_ids", "metric_ids"):
            values = tuple(getattr(self, name))
            for value in values:
                require_identifier(value, name)
            require_unique(values, name)
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class CoverageVector(CanonicalModel):
    dimensions: Mapping[str, str]

    def __post_init__(self) -> None:
        dimensions = dict(self.dimensions)
        if not dimensions:
            raise ValueError("coverage vector must not be empty")
        for name, value in dimensions.items():
            require_identifier(name, "coverage dimension")
            require_identifier(value, f"coverage dimension {name}")
        object.__setattr__(self, "dimensions", FrozenDict(dimensions))


@dataclass(frozen=True, slots=True)
class ExperimentSpec(CanonicalModel):
    """One fully pinned experiment; friendly IDs are never cache identities."""

    experiment_id: str
    spec_version: str
    project: VersionIdentity
    scenario: VersionIdentity
    task: VersionIdentity
    system: SystemUnderTest
    suites: tuple[SuitePlan, ...]
    environment_digest: Sha256Digest | str
    level: EvaluationLevel | str
    composition: ExecutionComposition | str
    execution_mode: ExecutionMode | str = ExecutionMode.FRESH_PROCESS
    attempts: int = 1
    seeds: tuple[int, ...] = (0,)
    coverage: CoverageVector | None = None
    oracle_bindings: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.experiment_id, "experiment_id")
        require_identifier(self.spec_version, "spec_version")
        if self.project.content_digest is None or self.scenario.content_digest is None or self.task.content_digest is None:
            raise ValueError("project, task, and scenario identities must be content-pinned")
        suites = tuple(self.suites)
        if not suites:
            raise ValueError("experiment requires at least one suite")
        require_unique(tuple(s.suite_id for s in suites), "suite ids")
        if isinstance(self.attempts, bool) or self.attempts <= 0:
            raise ValueError("attempts must be positive")
        seeds = tuple(self.seeds)
        if len(seeds) != self.attempts or any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in seeds):
            raise ValueError("seeds must contain one non-negative integer per attempt")
        if len(set(seeds)) != len(seeds) and self.attempts > 1:
            raise ValueError("repeated attempts require distinct seeds")
        try:
            level = EvaluationLevel(self.level)
            composition = ExecutionComposition(self.composition)
            mode = ExecutionMode(self.execution_mode)
        except ValueError as exc:
            raise ValueError("invalid experiment level, composition, or execution mode") from exc
        digest = self.environment_digest if isinstance(self.environment_digest, Sha256Digest) else Sha256Digest(self.environment_digest)
        object.__setattr__(self, "suites", suites)
        object.__setattr__(self, "seeds", seeds)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "composition", composition)
        object.__setattr__(self, "execution_mode", mode)
        object.__setattr__(self, "environment_digest", digest)
        bindings = freeze_json(self.oracle_bindings)
        for suite_id, binding in bindings.items():
            require_identifier(suite_id, "oracle binding suite id")
            if not isinstance(binding, Mapping) or set(binding) != {"labels_digest", "oracle_implementation_digest"}:
                raise ValueError("oracle binding must pin labels and implementation digests")
            Sha256Digest(binding["labels_digest"]); Sha256Digest(binding["oracle_implementation_digest"])
        object.__setattr__(self, "oracle_bindings", bindings)

    @property
    def identity(self) -> VersionIdentity:
        return VersionIdentity(self.experiment_id, self.spec_version, self.content_digest)

    @property
    def cache_key(self) -> Sha256Digest:
        """The content key includes every field, unlike ``experiment_id``."""

        return self.content_digest
