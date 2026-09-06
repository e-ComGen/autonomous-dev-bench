"""Fault specifications and independently verifiable boundary evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from benchmark_core.identity import FrozenDict, freeze_json, require_identifier


@dataclass(frozen=True, slots=True)
class FaultSpec:
    fault_id: str
    seed: int = 0
    parameters: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.fault_id, "fault_id")
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True, slots=True)
class FaultEvidence:
    fault_id: str
    boundary: str
    triggered: bool
    observations: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.fault_id, "fault_id")
        require_identifier(self.boundary, "boundary")
        object.__setattr__(self, "observations", freeze_json(self.observations))


@runtime_checkable
class FaultHandle(Protocol):
    @property
    def evidence(self) -> FaultEvidence: ...
    def trigger(self, *args: object, **kwargs: object) -> object: ...


@runtime_checkable
class FaultInjector(Protocol):
    fault_id: str
    def arm(self, execution_context: object, fault_spec: FaultSpec) -> FaultHandle: ...
    def verify_triggered(self, evidence: FaultEvidence, fault_spec: FaultSpec) -> bool: ...
