"""Canonical research manifest for paired autonomous-coding experiments.

This schema owns scientific identity and fairness policy. Execution engines such
as Harbor are deliberately represented as replaceable implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from .identity import (
    CanonicalModel,
    CommitPin,
    FrozenDict,
    Sha256Digest,
    freeze_json,
    require_identifier,
    require_nonempty,
)


def _positive(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _non_negative(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class TaskManifest(CanonicalModel):
    dataset: str
    dataset_version: str
    task_id: str
    task_repo_commit: CommitPin | str
    environment_image_digest: Sha256Digest | str
    evaluator_version: str

    def __post_init__(self) -> None:
        require_identifier(self.dataset, "dataset")
        require_identifier(self.dataset_version, "dataset_version")
        require_identifier(self.task_id, "task_id")
        require_identifier(self.evaluator_version, "evaluator_version")
        object.__setattr__(
            self,
            "task_repo_commit",
            self.task_repo_commit if isinstance(self.task_repo_commit, CommitPin) else CommitPin(self.task_repo_commit),
        )
        object.__setattr__(
            self,
            "environment_image_digest",
            self.environment_image_digest
            if isinstance(self.environment_image_digest, Sha256Digest)
            else Sha256Digest(self.environment_image_digest),
        )


@dataclass(frozen=True, slots=True)
class AgentManifest(CanonicalModel):
    implementation: str
    commit: CommitPin | str
    configuration: Mapping[str, object] = field(default_factory=FrozenDict)
    ablation_flags: Mapping[str, bool] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.implementation, "agent implementation")
        object.__setattr__(self, "commit", self.commit if isinstance(self.commit, CommitPin) else CommitPin(self.commit))
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        flags = dict(self.ablation_flags)
        for name, enabled in flags.items():
            require_identifier(name, "ablation flag")
            if not isinstance(enabled, bool):
                raise ValueError("ablation flags must be boolean")
        object.__setattr__(self, "ablation_flags", FrozenDict(flags))


@dataclass(frozen=True, slots=True)
class ModelManifest(CanonicalModel):
    identifier: str
    provider_route: str
    decoding: Mapping[str, object] = field(default_factory=FrozenDict)
    pricing_snapshot: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.identifier, "model identifier")
        require_nonempty(self.provider_route, "provider_route")
        object.__setattr__(self, "decoding", freeze_json(self.decoding))
        object.__setattr__(self, "pricing_snapshot", freeze_json(self.pricing_snapshot))


@dataclass(frozen=True, slots=True)
class BudgetManifest(CanonicalModel):
    input_token_cap: int
    output_token_cap: int
    total_model_token_cap: int
    max_requests: int
    wall_time_seconds: int
    patch_byte_cap: int

    def __post_init__(self) -> None:
        for name in (
            "input_token_cap",
            "output_token_cap",
            "total_model_token_cap",
            "max_requests",
            "wall_time_seconds",
            "patch_byte_cap",
        ):
            _positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ExecutionManifest(CanonicalModel):
    engine: str
    engine_version: str
    provider: str
    network_policy: str
    resource_policy: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        for name in ("engine", "engine_version", "provider", "network_policy"):
            require_identifier(getattr(self, name), name)
        object.__setattr__(self, "resource_policy", freeze_json(self.resource_policy))


@dataclass(frozen=True, slots=True)
class TrialManifest(CanonicalModel):
    repeat_index: int
    seed: int
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        _non_negative(self.repeat_index, "repeat_index")
        _non_negative(self.seed, "seed")
        for name in ("started_at", "finished_at"):
            value = getattr(self, name)
            if value is not None:
                require_nonempty(value, name)


@dataclass(frozen=True, slots=True)
class TrialOutputs(CanonicalModel):
    patch_digest: Sha256Digest | str
    trajectory_digest: Sha256Digest | str
    telemetry_digest: Sha256Digest | str
    evaluator_result: str

    def __post_init__(self) -> None:
        for name in ("patch_digest", "trajectory_digest", "telemetry_digest"):
            value = getattr(self, name)
            object.__setattr__(self, name, value if isinstance(value, Sha256Digest) else Sha256Digest(value))
        require_identifier(self.evaluator_result, "evaluator_result")


@dataclass(frozen=True, slots=True)
class ExperimentManifest(CanonicalModel):
    """One immutable experiment identity plus optional finalized trial outputs."""

    experiment_id: str
    task: TaskManifest
    agent: AgentManifest
    model: ModelManifest
    budget: BudgetManifest
    execution: ExecutionManifest
    trial: TrialManifest
    outputs: TrialOutputs | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        require_identifier(self.experiment_id, "experiment_id")
        require_identifier(self.schema_version, "schema_version")
        if self.trial.finished_at is not None and self.outputs is None:
            raise ValueError("finished trials require outputs")
        if self.outputs is not None and self.trial.finished_at is None:
            raise ValueError("outputs require a finished trial timestamp")

    @property
    def identity(self) -> Sha256Digest:
        return self.content_digest

    def finalize(self, outputs: TrialOutputs, finished_at: str) -> "ExperimentManifest":
        require_nonempty(finished_at, "finished_at")
        return replace(self, trial=replace(self.trial, finished_at=finished_at), outputs=outputs)
