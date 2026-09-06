"""Independent Auto-Zoning benchmark suite (B7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from benchmark_core.experiment import SuitePlan
from benchmark_core.identity import FrozenDict, freeze_json, require_identifier, require_unique
from benchmark_core.result import HardGate, OracleResult, RunStatus, SuiteResult, SystemObservation

SUITE_ID = "auto_zoning"
SUITE_VERSION = "3"
ADAPTER_ID = "auto_zoning.production_api.v3"
INPUT_CHECKPOINT = "task_ready"
ORACLE_IDS = (
    "responsibility_ground_truth.v4",
    "ownership_ground_truth.v3",
    "boundary_constraints.v2",
)
HARD_GATE_IDS = ("no_unauthorized_owner_assignment",)
METRIC_IDS = (
    "auto_zoning.responsibility_precision", "auto_zoning.responsibility_recall",
    "auto_zoning.ownership_accuracy", "auto_zoning.ownership_recall",
    "auto_zoning.unauthorized_owner_assignments", "auto_zoning.unauthorized_cross_zone_writes",
    "auto_zoning.cross_zone_false_positive", "auto_zoning.boundary_recall",
    "auto_zoning.proposal_mass", "auto_zoning.partial_mass", "auto_zoning.unknown_mass",
)
REQUIRED_OBSERVATIONS = (
    "responsibility_proposal",
    "ownership_proposal",
    "boundary_proposal",
    "proposal_mass",
    "partial_mass",
    "unknown_mass",
    "raw_output",
)


def plan() -> SuitePlan:
    """Return the B7 plan, bound to the pre-coder task-ready checkpoint."""
    return SuitePlan(
        SUITE_ID,
        SUITE_VERSION,
        INPUT_CHECKPOINT,
        ADAPTER_ID,
        ORACLE_IDS,
        REQUIRED_OBSERVATIONS,
        HARD_GATE_IDS,
        adapter_version="4",
        policy_version="4",
        acceptance_version="4",
        global_hard_gate_ids=("unauthorized_cross_zone_write", "lost_required_verification", "half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"),
        metric_ids=METRIC_IDS,
        labels_ref="private:auto_zoning/labels/v1",
    )


@dataclass(frozen=True, slots=True)
class ResponsibilityLabel:
    responsibility_id: str
    acceptable_zones: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.responsibility_id, "responsibility_id")
        zones = tuple(self.acceptable_zones)
        if not zones:
            raise ValueError("responsibility label requires an acceptable zone")
        for zone in zones:
            require_identifier(zone, "acceptable zone")
        require_unique(zones, "acceptable zones")
        object.__setattr__(self, "acceptable_zones", zones)


@dataclass(frozen=True, slots=True)
class AcceptableZoneSet:
    """One independently accepted whole-repository zoning alternative."""

    zone_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        zones = tuple(self.zone_ids)
        if not zones:
            raise ValueError("acceptable zone set must not be empty")
        for zone in zones:
            require_identifier(zone, "zone id")
        require_unique(zones, "zone ids")
        object.__setattr__(self, "zone_ids", zones)


@dataclass(frozen=True, slots=True)
class ResponsibilityZoneAssignment:
    responsibility_id: str
    zone_id: str

    def __post_init__(self) -> None:
        require_identifier(self.responsibility_id, "responsibility_id")
        require_identifier(self.zone_id, "zone_id")


@dataclass(frozen=True, slots=True)
class AcceptableZoningAlternative:
    """One coherent complete responsibility-to-zone oracle alternative."""

    assignments: tuple[ResponsibilityZoneAssignment, ...]
    boundaries: tuple["BoundaryConstraint", ...] = ()

    def __post_init__(self) -> None:
        assignments = tuple(self.assignments)
        boundaries = tuple(self.boundaries)
        if not assignments:
            raise ValueError("acceptable zoning alternative must not be empty")
        require_unique(tuple(item.responsibility_id for item in assignments), "alternative responsibilities")
        require_unique(
            tuple(f"{item.source_zone}->{item.target_zone}" for item in boundaries),
            "alternative boundary constraints",
        )
        zones = {item.zone_id for item in assignments}
        if any(item.source_zone not in zones or item.target_zone not in zones for item in boundaries):
            raise ValueError("alternative boundary must connect zones in that alternative")
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "boundaries", boundaries)


@dataclass(frozen=True, slots=True)
class BoundaryConstraint:
    source_zone: str
    target_zone: str
    allowed: bool

    def __post_init__(self) -> None:
        require_identifier(self.source_zone, "source_zone")
        require_identifier(self.target_zone, "target_zone")
        if self.source_zone == self.target_zone:
            raise ValueError("boundary constraint must connect distinct zones")


@dataclass(frozen=True, slots=True)
class ZoningOracleContext:
    """Private, independently typed truth unavailable to the adapter."""

    responsibilities: tuple[ResponsibilityLabel, ...]
    acceptable_zone_sets: tuple[AcceptableZoneSet, ...]
    boundaries: tuple[BoundaryConstraint, ...]
    unauthorized_cross_zone_writes: int = 0
    acceptable_alternatives: tuple[AcceptableZoningAlternative, ...] = ()
    labels_ref: str = "private:auto_zoning/labels/v1"

    def __post_init__(self) -> None:
        responsibilities = tuple(self.responsibilities)
        alternatives = tuple(self.acceptable_zone_sets)
        coherent_alternatives = tuple(self.acceptable_alternatives)
        boundaries = tuple(self.boundaries)
        require_unique(tuple(item.responsibility_id for item in responsibilities), "responsibility labels")
        require_unique(
            tuple(f"{item.source_zone}->{item.target_zone}" for item in boundaries),
            "boundary constraints",
        )
        responsibility_ids = {item.responsibility_id for item in responsibilities}
        for alternative in coherent_alternatives:
            actual = {item.responsibility_id for item in alternative.assignments}
            if actual != responsibility_ids:
                raise ValueError("acceptable zoning alternative must assign every responsibility exactly once")
        if isinstance(self.unauthorized_cross_zone_writes, bool) or self.unauthorized_cross_zone_writes < 0:
            raise ValueError("unauthorized_cross_zone_writes must be a non-negative integer")
        object.__setattr__(self, "responsibilities", responsibilities)
        object.__setattr__(self, "acceptable_zone_sets", alternatives)
        object.__setattr__(self, "acceptable_alternatives", coherent_alternatives)
        object.__setattr__(self, "boundaries", boundaries)


@dataclass(frozen=True, slots=True)
class OwnershipProposal:
    responsibility_id: str
    zone_id: str
    mass: float = 1.0

    def __post_init__(self) -> None:
        require_identifier(self.responsibility_id, "responsibility_id")
        require_identifier(self.zone_id, "zone_id")
        if not 0.0 <= self.mass <= 1.0:
            raise ValueError("proposal mass must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class BoundaryProposal:
    source_zone: str
    target_zone: str
    mass: float = 1.0

    def __post_init__(self) -> None:
        require_identifier(self.source_zone, "source_zone")
        require_identifier(self.target_zone, "target_zone")
        if not 0.0 <= self.mass <= 1.0:
            raise ValueError("proposal mass must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ZoningAdapterResult:
    ownership: tuple[OwnershipProposal, ...] = ()
    boundaries: tuple[BoundaryProposal, ...] = ()
    proposal_mass: float = 0.0
    partial_mass: float = 0.0
    unknown_mass: float = 1.0
    raw_output: object = None
    raw_fields: Mapping[str, object] = field(default_factory=FrozenDict)
    authoritative: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        ownership = tuple(self.ownership)
        boundaries = tuple(self.boundaries)
        for name in ("proposal_mass", "partial_mass", "unknown_mass"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if abs(self.proposal_mass + self.partial_mass + self.unknown_mass - 1.0) > 1e-9:
            raise ValueError("proposal, partial and unknown mass must sum to 1")
        require_unique(tuple(item.responsibility_id for item in ownership), "ownership assignments")
        require_unique(tuple(f"{item.source_zone}->{item.target_zone}" for item in boundaries), "boundary proposals")
        object.__setattr__(self, "ownership", ownership)
        object.__setattr__(self, "boundaries", boundaries)
        object.__setattr__(self, "raw_output", freeze_json(self.raw_output))
        object.__setattr__(self, "raw_fields", freeze_json(self.raw_fields))
        # Production output is always advisory, even if raw fields say otherwise.
        object.__setattr__(self, "authoritative", False)

    def observation(self) -> SystemObservation:
        raw = self.raw_output if isinstance(self.raw_output, Mapping) else {}
        raw_status = str(raw.get("semantic_status", raw.get("status", raw.get("process_status", "")))).upper()
        if raw_status == "STALE_SOURCE" or raw.get("snapshot_binding_valid") is False:
            status = RunStatus.INVALID_EXPERIMENT
        elif raw_status in {"WORKER_FAILED", "FAILED"} or not raw:
            status = RunStatus.INFRA_FAILURE
        else:
            status = RunStatus.PASS
        return SystemObservation(
            status,
            attributes={
                "responsibility_proposal": tuple(item.responsibility_id for item in self.ownership),
                "ownership_proposal": self.ownership,
                "boundary_proposal": self.boundaries,
                "proposal_mass": self.proposal_mass,
                "partial_mass": self.partial_mass,
                "unknown_mass": self.unknown_mass,
                "authoritative": False,
                "raw_output": self.raw_output,
                "raw_fields": self.raw_fields,
            },
        )


class AutoZoningSuite:
    suite_id = SUITE_ID
    suite_version = SUITE_VERSION
    adapter_id = ADAPTER_ID

    @staticmethod
    def plan(scenario: object | None = None) -> SuitePlan:
        return plan()

    def evaluate(
        self,
        scenario: object,
        observation: SystemObservation | ZoningOracleContext | None = None,
        oracle_context: ZoningOracleContext | None = None,
    ) -> SuiteResult:
        """Evaluate platform observations without exposing private labels to the SUT."""
        if isinstance(scenario, ZoningAdapterResult):
            proposal = scenario
            context = observation
            observation_status = RunStatus.PASS
        else:
            if not isinstance(observation, SystemObservation):
                raise TypeError("platform evaluation requires a SystemObservation")
            attrs = observation.attributes
            observation_status = observation.status
            ownership = tuple(
                item if isinstance(item, OwnershipProposal) else OwnershipProposal(
                    str(item["responsibility_id"]), str(item["zone_id"]), float(item.get("mass", 1.0))
                )
                for item in attrs.get("ownership_proposal", ())
            )
            boundaries = tuple(
                item if isinstance(item, BoundaryProposal) else BoundaryProposal(
                    str(item["source_zone"]), str(item["target_zone"]), float(item.get("mass", 1.0))
                )
                for item in attrs.get("boundary_proposal", ())
            )
            proposal = ZoningAdapterResult(
                ownership=ownership,
                boundaries=boundaries,
                proposal_mass=float(attrs.get("proposal_mass", 0.0)),
                partial_mass=float(attrs.get("partial_mass", 0.0)),
                unknown_mass=float(attrs.get("unknown_mass", 1.0)),
                raw_output=attrs.get("raw_output"),
                raw_fields=attrs.get("raw_fields", {}),
            )
            context = oracle_context
        if not isinstance(context, ZoningOracleContext):
            raise TypeError("Auto-Zoning requires a private ZoningOracleContext")
        if observation_status is not RunStatus.PASS:
            failed_oracles = tuple(
                OracleResult(oracle_id, oracle_id.rsplit(".", 1)[-1], observation_status, message="system observation was not evaluable")
                for oracle_id in ORACLE_IDS
            )
            return SuiteResult(SUITE_ID, SUITE_VERSION, observation_status, failed_oracles)
        labels = {item.responsibility_id: item for item in context.responsibilities}
        proposed_ids = {item.responsibility_id for item in proposal.ownership if item.mass > 0}
        true_ids = set(labels)
        tp = len(proposed_ids & true_ids)
        fp = len(proposed_ids - true_ids)
        fn = len(true_ids - proposed_ids)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0

        considered = [item for item in proposal.ownership if item.mass > 0 and item.responsibility_id in labels]
        correct = [item for item in considered if item.zone_id in labels[item.responsibility_id].acceptable_zones]
        ownership_accuracy = len(correct) / len(considered) if considered else (1.0 if not labels else 0.0)
        unauthorized = [item for item in considered if item.zone_id not in labels[item.responsibility_id].acceptable_zones]

        proposed_zone_ids = {item.zone_id for item in proposal.ownership if item.mass > 0}
        proposed_assignment = {
            item.responsibility_id: item.zone_id for item in proposal.ownership if item.mass > 0
        }
        matched_alternative = next((
            alternative for alternative in context.acceptable_alternatives
            if proposed_assignment == {
                item.responsibility_id: item.zone_id for item in alternative.assignments
            }
        ), None)
        if context.acceptable_alternatives:
            accepted_zone_set = matched_alternative is not None
            allowed_constraints = (
                matched_alternative.boundaries if matched_alternative is not None
                else tuple(item for alternative in context.acceptable_alternatives for item in alternative.boundaries)
            )
        else:
            accepted_zone_set = (
                not context.acceptable_zone_sets
                or any(proposed_zone_ids == set(alternative.zone_ids) for alternative in context.acceptable_zone_sets)
            )
            allowed_constraints = context.boundaries
        rules = {(item.source_zone, item.target_zone): item.allowed for item in allowed_constraints}
        proposed_pairs = {(item.source_zone, item.target_zone) for item in proposal.boundaries if item.mass > 0}
        required_pairs = {
            pair for pair, allowed in rules.items()
            if allowed and pair[0] in proposed_zone_ids and pair[1] in proposed_zone_ids
        }
        boundary_false_positives = [
            item for item in proposal.boundaries
            if item.mass > 0 and rules.get((item.source_zone, item.target_zone)) is not True
        ]
        missing_boundaries = tuple(sorted(required_pairs - proposed_pairs))
        responsibility_ok = not fp and not fn
        ownership_ok = responsibility_ok and not unauthorized and len(correct) == len(labels) and accepted_zone_set
        boundary_ok = not boundary_false_positives and not missing_boundaries
        oracles = (
            OracleResult(ORACLE_IDS[0], "v4", RunStatus.PASS if responsibility_ok else RunStatus.FAIL,
                         {"precision": precision, "recall": recall}),
            OracleResult(ORACLE_IDS[1], "v3", RunStatus.PASS if ownership_ok else RunStatus.FAIL,
                         {"accuracy": ownership_accuracy, "unauthorized_assignments": len(unauthorized),
                          "accepted_zone_set": accepted_zone_set}),
            OracleResult(ORACLE_IDS[2], "v2", RunStatus.PASS if boundary_ok else RunStatus.FAIL,
                         {"cross_zone_false_positive": len(boundary_false_positives),
                          "missing_required_boundaries": missing_boundaries}),
        )
        # Wrong owner assignment is a suite failure. The global cross-zone-write
        # gate is reserved for an observed write, not merely a bad proposal.
        gates = (
            (HardGate.UNAUTHORIZED_CROSS_ZONE_WRITE,)
            if context.unauthorized_cross_zone_writes > 0
            else ()
        )
        passed = all(item.status is RunStatus.PASS for item in oracles) and not gates
        return SuiteResult(
            SUITE_ID,
            SUITE_VERSION,
            RunStatus.PASS if passed else RunStatus.FAIL,
            oracles,
            gates,
            metrics={
                "auto_zoning.responsibility_precision": precision,
                "auto_zoning.responsibility_recall": recall,
                "auto_zoning.ownership_accuracy": ownership_accuracy,
                "auto_zoning.ownership_recall": len(correct) / len(labels) if labels else 1.0,
                "auto_zoning.unauthorized_owner_assignments": len(unauthorized),
                "auto_zoning.unauthorized_cross_zone_writes": context.unauthorized_cross_zone_writes,
                "auto_zoning.cross_zone_false_positive": len(boundary_false_positives),
                "auto_zoning.boundary_recall": len(required_pairs & proposed_pairs) / len(required_pairs) if required_pairs else 1.0,
                "auto_zoning.proposal_mass": proposal.proposal_mass,
                "auto_zoning.partial_mass": proposal.partial_mass,
                "auto_zoning.unknown_mass": proposal.unknown_mass,
            },
            suite_gate_outcomes={"no_unauthorized_owner_assignment": not unauthorized},
            global_gate_outcomes={"unauthorized_cross_zone_write": not gates, "lost_required_verification": True},
        )
