"""Independent observations, oracle verdicts, stage and suite results.

The model intentionally has no cross-suite scalar score.  Capability metrics
remain vectors and hard-gate failures are non-compensable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Mapping

from .identity import CanonicalModel, FrozenDict, Sha256Digest, freeze_json, require_identifier, require_unique


class RunStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFRA_FAILURE = "INFRA_FAILURE"
    BASELINE_BROKEN = "BASELINE_BROKEN"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"
    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"


class HardGate(str, Enum):
    FALSE_SAFE_CERTIFICATE = "false_safe_certificate"
    UNAUTHORIZED_CROSS_ZONE_WRITE = "unauthorized_cross_zone_write"
    HALF_APPLIED_TRANSACTION = "half_applied_transaction"
    ACCEPTED_STALE_CANDIDATE = "accepted_stale_candidate"
    LOST_REQUIRED_VERIFICATION = "lost_required_verification"
    EVIDENCE_INTEGRITY_FAILURE = "evidence_integrity_failure"


FORBIDDEN_GLOBAL_AGGREGATES = frozenset({
    "autonomous_dev_score",
    "autonomousdevscore",
})
_ARTIFACT_REF = re.compile(r"^(?:cas:)?sha256:[0-9a-f]{64}$")


def _artifact_ref(value: Sha256Digest | str) -> str:
    text = str(value)
    if not text.startswith("cas:sha256:") or not _ARTIFACT_REF.fullmatch(text):
        raise ValueError("stored artifact must be CAS-backed: cas:sha256:<digest>")
    return text


def _evidence_ref(value: Sha256Digest | str) -> str:
    text = str(value)
    if not text.startswith("cas:sha256:") or not _ARTIFACT_REF.fullmatch(text):
        raise ValueError("evidence reference must be CAS-backed: cas:sha256:<digest>")
    return text


def _status(value: RunStatus | str) -> RunStatus:
    try:
        return RunStatus(value)
    except ValueError as exc:
        raise ValueError(f"unknown run status: {value!r}") from exc


def _immutable_metrics(values: Mapping[str, object], name: str) -> object:
    frozen = freeze_json(values)

    def reject_global_score(value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = key.casefold().replace("-", "_").replace(" ", "_")
                if normalized in FORBIDDEN_GLOBAL_AGGREGATES:
                    raise ValueError("global aggregate AUTONOMOUS_DEV_SCORE semantics are forbidden")
                reject_global_score(item)
        elif isinstance(value, tuple):
            for item in value:
                reject_global_score(item)

    reject_global_score(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class SystemObservation(CanonicalModel):
    """Neutral capture of system behaviour, before oracle interpretation."""

    status: RunStatus | str
    output_artifact: Sha256Digest | str | None = None
    trace_artifact: Sha256Digest | str | None = None
    changed_tree_digest: Sha256Digest | str | None = None
    metrics_artifact: Sha256Digest | str | None = None
    attributes: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        for name in ("output_artifact", "trace_artifact", "metrics_artifact"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _artifact_ref(value))
        if self.changed_tree_digest is not None:
            object.__setattr__(self, "changed_tree_digest", str(Sha256Digest(str(self.changed_tree_digest))))
        object.__setattr__(self, "attributes", _immutable_metrics(self.attributes, "attributes"))


@dataclass(frozen=True, slots=True)
class OracleResult(CanonicalModel):
    """Verdict from one independently versioned oracle."""

    oracle_id: str
    oracle_version: str
    status: RunStatus | str
    measurements: Mapping[str, object] = field(default_factory=FrozenDict)
    evidence_refs: tuple[Sha256Digest | str, ...] = ()
    message: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.oracle_id, "oracle_id")
        require_identifier(self.oracle_version, "oracle_version")
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "measurements", _immutable_metrics(self.measurements, "measurements"))
        refs = tuple(_evidence_ref(ref) for ref in self.evidence_refs)
        require_unique(refs, "evidence_refs")
        object.__setattr__(self, "evidence_refs", refs)


@dataclass(frozen=True, slots=True)
class StageResult(CanonicalModel):
    """Diagnostic result for one execution-DAG stage."""

    stage_id: str
    status: RunStatus | str
    observation: SystemObservation | None = None
    oracle_results: tuple[OracleResult, ...] = ()
    evidence_refs: tuple[Sha256Digest | str, ...] = ()
    details: Mapping[str, object] = field(default_factory=FrozenDict)
    component: str | None = None
    input_fingerprint: Sha256Digest | str | None = None
    output_fingerprint: Sha256Digest | str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    trace_refs: tuple[Sha256Digest | str, ...] = ()
    failure_class: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.stage_id, "stage_id")
        object.__setattr__(self, "status", _status(self.status))
        results = tuple(self.oracle_results)
        require_unique(tuple(r.oracle_id for r in results), "stage oracle ids")
        refs = tuple(_evidence_ref(ref) for ref in self.evidence_refs)
        trace_refs = tuple(_artifact_ref(ref) for ref in self.trace_refs)
        require_unique(refs, "stage evidence refs")
        require_unique(trace_refs, "stage trace refs")
        component = self.component or self.stage_id
        require_identifier(component, "component")
        for name in ("input_fingerprint", "output_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, str(Sha256Digest(str(value))))
        if (self.started_at is None) != (self.completed_at is None):
            raise ValueError("stage timestamps must be supplied together")
        object.__setattr__(self, "component", component)
        object.__setattr__(self, "oracle_results", results)
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "trace_refs", trace_refs)
        object.__setattr__(self, "details", _immutable_metrics(self.details, "details"))


@dataclass(frozen=True, slots=True)
class SuiteResult(CanonicalModel):
    """A suite-local capability result, never an aggregate across capabilities."""

    suite_id: str
    suite_version: str
    status: RunStatus | str
    oracle_results: tuple[OracleResult, ...]
    hard_gate_failures: tuple[HardGate | str, ...] = ()
    metrics: Mapping[str, object] = field(default_factory=FrozenDict)
    stage_results: tuple[StageResult, ...] = ()
    suite_gate_outcomes: Mapping[str, bool] = field(default_factory=FrozenDict)
    global_gate_outcomes: Mapping[str, bool] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.suite_id, "suite_id")
        require_identifier(self.suite_version, "suite_version")
        status = _status(self.status)
        oracle_results = tuple(self.oracle_results)
        require_unique(tuple(result.oracle_id for result in oracle_results), "suite oracle ids")
        try:
            gates = tuple(gate if isinstance(gate, HardGate) else HardGate(gate) for gate in self.hard_gate_failures)
        except ValueError as exc:
            raise ValueError("hard_gate_failures contains an unknown hard gate") from exc
        require_unique(tuple(gate.value for gate in gates), "hard_gate_failures")
        if gates and status is RunStatus.PASS:
            raise ValueError("a non-compensable hard-gate failure cannot have PASS status")
        if status is RunStatus.PASS and any(result.status is not RunStatus.PASS for result in oracle_results):
            raise ValueError("suite cannot PASS when an independent oracle did not pass")
        stages = tuple(self.stage_results)
        require_unique(tuple(stage.stage_id for stage in stages), "stage ids")
        suite_gates = dict(self.suite_gate_outcomes)
        global_gates = dict(self.global_gate_outcomes)
        for name, passed in (*suite_gates.items(), *global_gates.items()):
            require_identifier(name, "gate id")
            if not isinstance(passed, bool):
                raise ValueError("gate outcomes must be boolean")
        failed_global = {gate.value for gate in gates}
        if global_gates and failed_global != {name for name, passed in global_gates.items() if not passed}:
            raise ValueError("hard_gate_failures must equal failed global gate outcomes")
        if status is RunStatus.PASS and any(not passed for passed in (*suite_gates.values(), *global_gates.values())):
            raise ValueError("suite cannot PASS when any declared gate outcome is false")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "oracle_results", oracle_results)
        object.__setattr__(self, "hard_gate_failures", gates)
        object.__setattr__(self, "metrics", _immutable_metrics(self.metrics, "metrics"))
        object.__setattr__(self, "stage_results", stages)
        object.__setattr__(self, "suite_gate_outcomes", FrozenDict(suite_gates))
        object.__setattr__(self, "global_gate_outcomes", FrozenDict(global_gates))

    @property
    def passed(self) -> bool:
        return self.status is RunStatus.PASS and not self.hard_gate_failures


@dataclass(frozen=True, slots=True)
class RunResult(CanonicalModel):
    """Run envelope preserving independent suite results without a global score."""

    run_id: str
    experiment_digest: Sha256Digest | str
    status: RunStatus | str
    suite_results: tuple[SuiteResult, ...]

    def __post_init__(self) -> None:
        require_identifier(self.run_id, "run_id")
        digest = self.experiment_digest if isinstance(self.experiment_digest, Sha256Digest) else Sha256Digest(self.experiment_digest)
        status = _status(self.status)
        suites = tuple(self.suite_results)
        require_unique(tuple(suite.suite_id for suite in suites), "run suite ids")
        if status is RunStatus.PASS and any(not suite.passed for suite in suites):
            raise ValueError("run cannot PASS unless every independent suite passes")
        object.__setattr__(self, "experiment_digest", digest)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "suite_results", suites)
