"""Answer-free scenario composition with validated checkpoint DAGs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .identity import CanonicalModel, FrozenDict, VersionIdentity, freeze_json, require_identifier, require_unique

_FORBIDDEN_ANSWER_KEYS = {
    "answer", "expected", "expectations", "expected_answer", "expected_output",
    "ground_truth", "labels", "oracle", "oracle_result", "verdict",
}


class ExecutionMode(str, Enum):
    SAME_PROCESS = "same_process"
    FRESH_PROCESS = "fresh_process"
    RESTART_PROCESS = "restart_process"


@dataclass(frozen=True, slots=True)
class CheckpointSpec(CanonicalModel):
    checkpoint_id: str
    depends_on: tuple[str, ...] = ()
    description: str = ""
    overlays: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.checkpoint_id, "checkpoint_id")
        dependencies = tuple(self.depends_on)
        for dependency in dependencies:
            require_identifier(dependency, "checkpoint dependency")
        require_unique(dependencies, "checkpoint dependencies")
        if self.checkpoint_id in dependencies:
            raise ValueError("checkpoint cannot depend on itself")
        overlays = tuple(self.overlays)
        for overlay in overlays:
            require_identifier(overlay, "checkpoint overlay")
        require_unique(overlays, "checkpoint overlays")
        object.__setattr__(self, "depends_on", dependencies)
        object.__setattr__(self, "overlays", overlays)


@dataclass(frozen=True, slots=True)
class MutationApplication(CanonicalModel):
    mutation_id: str
    input_checkpoint: str
    output_checkpoint: str
    seed: int
    parameters: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        for name in ("mutation_id", "input_checkpoint", "output_checkpoint"):
            require_identifier(getattr(self, name), name)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("mutation seed must be a non-negative integer")
        frozen = freeze_json(self.parameters)
        _reject_answer_data(frozen)
        object.__setattr__(self, "parameters", frozen)


@dataclass(frozen=True, slots=True)
class FaultApplication(CanonicalModel):
    fault_id: str
    checkpoint: str
    parameters: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.fault_id, "fault_id")
        require_identifier(self.checkpoint, "checkpoint")
        frozen = freeze_json(self.parameters)
        _reject_answer_data(frozen)
        object.__setattr__(self, "parameters", frozen)


@dataclass(frozen=True, slots=True)
class ScenarioExecution(CanonicalModel):
    mode: ExecutionMode | str = ExecutionMode.FRESH_PROCESS
    timeout_seconds: int | None = None
    environment: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "mode", ExecutionMode(self.mode))
        except ValueError as exc:
            raise ValueError(f"unsupported execution mode: {self.mode!r}") from exc
        if self.timeout_seconds is not None and (
            isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive when supplied")
        frozen = freeze_json(self.environment)
        _reject_answer_data(frozen)
        object.__setattr__(self, "environment", frozen)


@dataclass(frozen=True, slots=True)
class ScenarioSpec(CanonicalModel):
    """Declarative world construction, intentionally containing no verdict data."""

    scenario_id: str
    spec_version: str
    project_id: str
    task_id: str | None
    checkpoints: tuple[CheckpointSpec, ...]
    input_checkpoint: str
    mutations: tuple[MutationApplication, ...] = ()
    faults: tuple[FaultApplication, ...] = ()
    execution: ScenarioExecution = field(default_factory=ScenarioExecution)
    suite_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        for name in ("scenario_id", "spec_version", "project_id", "input_checkpoint"):
            require_identifier(getattr(self, name), name)
        if self.task_id is not None:
            require_identifier(self.task_id, "task_id")
        checkpoints = tuple(self.checkpoints)
        if not checkpoints:
            raise ValueError("scenario requires at least one checkpoint")
        mutations = tuple(self.mutations)
        faults = tuple(self.faults)
        suites = tuple(self.suite_ids)
        for suite_id in suites:
            require_identifier(suite_id, "suite_id")
        require_unique(suites, "suite_ids")
        object.__setattr__(self, "checkpoints", checkpoints)
        object.__setattr__(self, "mutations", mutations)
        object.__setattr__(self, "faults", faults)
        object.__setattr__(self, "suite_ids", suites)
        metadata = freeze_json(self.metadata)
        _reject_answer_data(metadata)
        object.__setattr__(self, "metadata", metadata)
        self._validate_dag()

    @property
    def identity(self) -> VersionIdentity:
        return VersionIdentity(self.scenario_id, self.spec_version, self.content_digest)

    def _validate_dag(self) -> None:
        by_id = {checkpoint.checkpoint_id: checkpoint for checkpoint in self.checkpoints}
        if len(by_id) != len(self.checkpoints):
            raise ValueError("checkpoint ids must be unique")
        if self.input_checkpoint not in by_id:
            raise ValueError("input_checkpoint must name a declared checkpoint")
        for checkpoint in self.checkpoints:
            missing = set(checkpoint.depends_on) - by_id.keys()
            if missing:
                raise ValueError(f"checkpoint {checkpoint.checkpoint_id!r} has unknown dependencies: {sorted(missing)!r}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(checkpoint_id: str) -> None:
            if checkpoint_id in visiting:
                raise ValueError("checkpoint graph must be acyclic")
            if checkpoint_id in visited:
                return
            visiting.add(checkpoint_id)
            for dependency in by_id[checkpoint_id].depends_on:
                visit(dependency)
            visiting.remove(checkpoint_id)
            visited.add(checkpoint_id)

        for checkpoint_id in by_id:
            visit(checkpoint_id)
        require_unique(tuple(mutation.mutation_id for mutation in self.mutations), "mutation ids")
        require_unique(tuple(mutation.output_checkpoint for mutation in self.mutations), "mutation output checkpoints")
        require_unique(tuple(fault.fault_id for fault in self.faults), "fault ids")
        declared_overlays = {
            overlay: checkpoint.checkpoint_id
            for checkpoint in self.checkpoints
            for overlay in checkpoint.overlays
            if overlay.startswith("mutation:")
        }
        if len(declared_overlays) != sum(
            overlay.startswith("mutation:") for checkpoint in self.checkpoints for overlay in checkpoint.overlays
        ):
            raise ValueError("mutation overlays must be unique")
        expected_overlays = {f"mutation:{mutation.mutation_id}": mutation.output_checkpoint for mutation in self.mutations}
        if declared_overlays != expected_overlays:
            raise ValueError("mutation applications and checkpoint overlays must form an exact bijection")
        for mutation in self.mutations:
            if mutation.input_checkpoint not in by_id or mutation.output_checkpoint not in by_id:
                raise ValueError(f"mutation {mutation.mutation_id!r} references an unknown checkpoint")
            if mutation.input_checkpoint not in by_id[mutation.output_checkpoint].depends_on:
                raise ValueError("mutation output checkpoint must depend directly on its input checkpoint")
        for fault in self.faults:
            if fault.checkpoint not in by_id:
                raise ValueError(f"fault {fault.fault_id!r} references an unknown checkpoint")


def _reject_answer_data(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_ANSWER_KEYS or normalized.startswith("expected_"):
                location = f"{path}.{key}" if path else key
                raise ValueError(f"scenario must be answer-free; forbidden field {location!r}")
            _reject_answer_data(item, f"{path}.{key}" if path else key)
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            _reject_answer_data(item, f"{path}[{index}]")
