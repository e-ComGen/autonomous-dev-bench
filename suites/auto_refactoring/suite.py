"""Independent Auto-Refactoring benchmark suite (B6).

The suite deliberately treats production output as an untrusted proposal.  All
safety and preservation verdicts are supplied by benchmark-owned context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from benchmark_core.experiment import SuitePlan
from benchmark_core.identity import FrozenDict, freeze_json, require_identifier, require_unique
from benchmark_core.result import HardGate, OracleResult, RunStatus, SuiteResult, SystemObservation

SUITE_ID = "auto_refactoring"
SUITE_VERSION = "4"
ADAPTER_ID = "auto_refactoring.production_api.v2"
INPUT_CHECKPOINT = "candidate_bad_dispatch"
ORACLE_IDS = (
    "mutation_presence.independent.v1",
    "design_opportunity.v3",
    "functional_regression.v2",
    "differential_behavior.v1",
    "public_api.v2",
)
HARD_GATE_IDS = ("no_false_safe", "semantic_preservation")
METRIC_IDS = (
    "auto_refactoring.detection_precision", "auto_refactoring.detection_recall",
    "auto_refactoring.detection_true_positive", "auto_refactoring.detection_false_positive",
    "auto_refactoring.detection_false_negative", "auto_refactoring.keep_current_accuracy",
    "auto_refactoring.keep_current_applicable", "auto_refactoring.keep_current_correct",
    "auto_refactoring.semantic_preservation", "auto_refactoring.claimed_safe",
    "auto_refactoring.false_safe", "core.changed_files", "core.wall_time",
)
REQUIRED_OBSERVATIONS = (
    "raw_output",
    "raw_status",
    "stdout",
    "stderr",
    "changed_paths",
)


def plan() -> SuitePlan:
    """Return the B6 plan, bound to the post-mutation candidate checkpoint."""
    return SuitePlan(
        SUITE_ID,
        SUITE_VERSION,
        INPUT_CHECKPOINT,
        ADAPTER_ID,
        ORACLE_IDS,
        REQUIRED_OBSERVATIONS,
        HARD_GATE_IDS,
        adapter_version="2",
        policy_version="4",
        acceptance_version="4",
        global_hard_gate_ids=("false_safe_certificate", "lost_required_verification", "half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"),
        metric_ids=METRIC_IDS,
        labels_ref="private:auto_refactoring/labels/v1",
    )


class RefactoringDecision(str, Enum):
    REMEDIATE = "REMEDIATE"
    KEEP_CURRENT = "KEEP_CURRENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RefactoringLabels:
    """Private suite labels; never sent to the production adapter."""

    mutation_present: bool
    design_opportunity: bool
    acceptable_remediation_families: tuple[str, ...] = ()
    keep_current_expected: bool = False

    def __post_init__(self) -> None:
        families = tuple(self.acceptable_remediation_families)
        for family in families:
            require_identifier(family, "remediation family")
        require_unique(families, "remediation families")
        if self.keep_current_expected and self.design_opportunity:
            raise ValueError("KEEP_CURRENT cannot be expected for a design opportunity")
        object.__setattr__(self, "acceptable_remediation_families", families)


@dataclass(frozen=True, slots=True)
class RefactoringOracleContext:
    """Independent oracle facts captured after the adapter has run."""

    labels: RefactoringLabels
    functional_preserved: bool
    differential_preserved: bool
    public_api_preserved: bool
    mutation_presence_verified: bool = True
    design_opportunity_verified: bool = True
    mutation_evidence: Mapping[str, object] = field(default_factory=FrozenDict)
    design_evidence: Mapping[str, object] = field(default_factory=FrozenDict)
    labels_ref: str = "private:auto_refactoring/labels/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutation_evidence", freeze_json(self.mutation_evidence))
        object.__setattr__(self, "design_evidence", freeze_json(self.design_evidence))


@dataclass(frozen=True, slots=True)
class RefactoringAdapterResult:
    """Neutral, lossless-enough normalization of an untrusted SUT response."""

    decision: RefactoringDecision | str = RefactoringDecision.UNKNOWN
    remediation_family: str | None = None
    changed_paths: tuple[str, ...] = ()
    wall_time_seconds: float = 0.0
    design_gate: str | None = None
    controller_recommendation: str | None = None
    remediation_families: tuple[str, ...] = ()
    selected_forms: tuple[str, ...] = ()
    opportunity_ids: tuple[str, ...] = ()
    opportunity_kinds: tuple[str, ...] = ()
    opportunity_gates: tuple[str, ...] = ()
    hard_unknowns: tuple[str, ...] = ()
    raw_status: object = None
    process_status: int | None = None
    certification_claim: object = None
    raw_output: object = None
    stdout: str = ""
    stderr: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.decision, RefactoringDecision):
            decision = self.decision
        else:
            try:
                decision = RefactoringDecision(str(self.decision).upper())
            except ValueError:
                decision = RefactoringDecision.UNKNOWN
        if self.remediation_family is not None:
            require_identifier(self.remediation_family, "remediation_family")
        if self.design_gate is not None:
            object.__setattr__(self, "design_gate", str(self.design_gate))
        if self.controller_recommendation is not None:
            object.__setattr__(
                self, "controller_recommendation", str(self.controller_recommendation)
            )
        paths = tuple(str(path) for path in self.changed_paths)
        require_unique(paths, "changed_paths")
        details = {
            "remediation_families": tuple(str(value) for value in self.remediation_families),
            "selected_forms": tuple(str(value) for value in self.selected_forms),
            "opportunity_ids": tuple(str(value) for value in self.opportunity_ids),
            "opportunity_kinds": tuple(str(value) for value in self.opportunity_kinds),
            "opportunity_gates": tuple(str(value) for value in self.opportunity_gates),
            "hard_unknowns": tuple(str(value) for value in self.hard_unknowns),
        }
        for field_name, values in details.items():
            object.__setattr__(self, field_name, values)
        if self.wall_time_seconds < 0:
            raise ValueError("wall_time_seconds cannot be negative")
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "changed_paths", paths)
        object.__setattr__(self, "raw_output", freeze_json(self.raw_output))
        object.__setattr__(self, "raw_status", freeze_json(self.raw_status))
        object.__setattr__(self, "certification_claim", freeze_json(self.certification_claim))

    def observation(self) -> SystemObservation:
        # Adapter health is distinct from any claimed safety/certification.
        if str(self.raw_status).upper() == "TIMEOUT" or self.raw_output is None:
            status = RunStatus.INFRA_FAILURE
        elif self.process_status not in (None, 0):
            status = RunStatus.FAIL
        else:
            status = RunStatus.PASS
        return SystemObservation(
            status,
            attributes={
                "decision": self.decision.value,
                "remediation_family": self.remediation_family,
                "design_gate": self.design_gate,
                "controller_recommendation": self.controller_recommendation,
                "remediation_families": self.remediation_families,
                "selected_forms": self.selected_forms,
                "opportunity_ids": self.opportunity_ids,
                "opportunity_kinds": self.opportunity_kinds,
                "opportunity_gates": self.opportunity_gates,
                "hard_unknowns": self.hard_unknowns,
                "changed_paths": self.changed_paths,
                "wall_time_seconds": self.wall_time_seconds,
                "raw_status": self.raw_status,
                "process_status": self.process_status,
                "certification_claim": self.certification_claim,
                "raw_output": self.raw_output,
                "stdout": self.stdout,
                "stderr": self.stderr,
            },
        )


class AutoRefactoringSuite:
    suite_id = SUITE_ID
    suite_version = SUITE_VERSION
    adapter_id = ADAPTER_ID

    @staticmethod
    def plan(scenario: object | None = None) -> SuitePlan:
        # Scenario identity is intentionally not used to obtain expected labels.
        return plan()

    def evaluate(
        self,
        scenario: object,
        observation: SystemObservation | RefactoringOracleContext | None = None,
        oracle_context: RefactoringOracleContext | None = None,
    ) -> SuiteResult:
        """Evaluate a neutral observation against suite-private facts.

        The two-argument ``evaluate(RefactoringAdapterResult, context)`` form is
        retained for direct component tests; the three-argument form implements
        the platform ``BenchmarkSuite`` protocol.
        """
        if isinstance(scenario, RefactoringAdapterResult):
            candidate = scenario
            context = observation
            observation_status = RunStatus.PASS
        else:
            if not isinstance(observation, SystemObservation):
                raise TypeError("platform evaluation requires a SystemObservation")
            attrs = observation.attributes
            observation_status = observation.status
            candidate = RefactoringAdapterResult(
                decision=attrs.get("decision", "UNKNOWN"),
                remediation_family=attrs.get("remediation_family"),
                changed_paths=tuple(attrs.get("changed_paths", ())),
                wall_time_seconds=float(attrs.get("wall_time_seconds", 0.0)),
                design_gate=attrs.get("design_gate"),
                controller_recommendation=attrs.get("controller_recommendation"),
                remediation_families=tuple(attrs.get("remediation_families", ())),
                selected_forms=tuple(attrs.get("selected_forms", ())),
                opportunity_ids=tuple(attrs.get("opportunity_ids", ())),
                opportunity_kinds=tuple(attrs.get("opportunity_kinds", ())),
                opportunity_gates=tuple(attrs.get("opportunity_gates", ())),
                hard_unknowns=tuple(attrs.get("hard_unknowns", ())),
                raw_status=attrs.get("raw_status"),
                process_status=attrs.get("process_status"),
                certification_claim=attrs.get("certification_claim"),
                raw_output=attrs.get("raw_output"),
                stdout=str(attrs.get("stdout", "")),
                stderr=str(attrs.get("stderr", "")),
            )
            context = oracle_context
        if not isinstance(context, RefactoringOracleContext):
            raise TypeError("Auto-Refactoring requires a private RefactoringOracleContext")
        if observation_status is not RunStatus.PASS:
            failed_oracles = tuple(
                OracleResult(oracle_id, oracle_id.rsplit(".", 1)[-1], observation_status, message="system observation was not evaluable")
                for oracle_id in ORACLE_IDS
            )
            return SuiteResult(SUITE_ID, SUITE_VERSION, observation_status, failed_oracles)
        labels = context.labels
        predicts_opportunity = candidate.decision is RefactoringDecision.REMEDIATE
        actual_opportunity = labels.design_opportunity
        tp = int(predicts_opportunity and actual_opportunity)
        fp = int(predicts_opportunity and not actual_opportunity)
        fn = int(not predicts_opportunity and actual_opportunity)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        keep_correct = candidate.decision is RefactoringDecision.KEEP_CURRENT and labels.keep_current_expected

        proposed_families = candidate.remediation_families or (
            (candidate.remediation_family,) if candidate.remediation_family is not None else ()
        )
        family_ok = (
            not predicts_opportunity
            or not labels.acceptable_remediation_families
            or any(family in labels.acceptable_remediation_families for family in proposed_families)
        )
        mutation_ok = context.mutation_presence_verified
        design_ok = context.design_opportunity_verified and predicts_opportunity == actual_opportunity and family_ok
        if labels.keep_current_expected:
            design_ok = design_ok and candidate.decision is RefactoringDecision.KEEP_CURRENT
        semantic_ok = context.functional_preserved and context.differential_preserved and context.public_api_preserved
        claim = candidate.certification_claim
        claimed_safe = bool(claim is True or (
            isinstance(claim, Mapping) and (claim.get("safe") is True or claim.get("certified") is True)
        ))
        false_safe = (
            candidate.decision is RefactoringDecision.KEEP_CURRENT and (labels.mutation_present or labels.design_opportunity)
        ) or (claimed_safe and not semantic_ok)

        oracle_values = (
            (ORACLE_IDS[0], mutation_ok, labels.mutation_present, context.mutation_evidence),
            (ORACLE_IDS[1], design_ok, actual_opportunity, context.design_evidence),
            (ORACLE_IDS[2], context.functional_preserved, context.functional_preserved, {}),
            (ORACLE_IDS[3], context.differential_preserved, context.differential_preserved, {}),
            (ORACLE_IDS[4], context.public_api_preserved, context.public_api_preserved, {}),
        )
        oracles = tuple(
            OracleResult(
                oracle_id,
                oracle_id.rsplit(".", 1)[-1],
                RunStatus.PASS if passed else RunStatus.FAIL,
                {"passed": passed, "independent_fact": fact, "evidence": evidence},
            )
            for oracle_id, passed, fact, evidence in oracle_values
        )
        gates: list[HardGate] = []
        if false_safe:
            gates.append(HardGate.FALSE_SAFE_CERTIFICATE)
        if not semantic_ok:
            # Core's closed gate taxonomy represents failed mandatory semantic
            # verification as LOST_REQUIRED_VERIFICATION.
            gates.append(HardGate.LOST_REQUIRED_VERIFICATION)
        passed = all(item.status is RunStatus.PASS for item in oracles) and not gates
        return SuiteResult(
            SUITE_ID,
            SUITE_VERSION,
            RunStatus.PASS if passed else RunStatus.FAIL,
            oracles,
            tuple(gates),
            metrics={
                "auto_refactoring.detection_precision": precision,
                "auto_refactoring.detection_recall": recall,
                "auto_refactoring.detection_true_positive": tp,
                "auto_refactoring.detection_false_positive": fp,
                "auto_refactoring.detection_false_negative": fn,
                "auto_refactoring.keep_current_accuracy": float(keep_correct) if labels.keep_current_expected else 1.0,
                "auto_refactoring.keep_current_applicable": int(labels.keep_current_expected),
                "auto_refactoring.keep_current_correct": int(keep_correct),
                "auto_refactoring.semantic_preservation": float(semantic_ok),
                "auto_refactoring.claimed_safe": int(claimed_safe),
                "auto_refactoring.false_safe": int(false_safe),
                "core.changed_files": len(candidate.changed_paths),
                "core.wall_time": candidate.wall_time_seconds,
            },
            suite_gate_outcomes={"no_false_safe": not false_safe, "semantic_preservation": semantic_ok},
            global_gate_outcomes={
                "false_safe_certificate": not false_safe,
                "lost_required_verification": semantic_ok,
            },
        )
