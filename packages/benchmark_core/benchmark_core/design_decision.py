"""Outcome-blind decision binding for the Phase 3D paired experiment.

D4 owns exact power calibration and D5 owns sensitivity reporting. This module
binds one explicitly selected pre-experiment sensitivity scenario to explicit
resource caps, produces a LOCKED-plan candidate, and records immutable evidence
for that decision. It never selects a scenario automatically and never reads
paid experiment outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .design_calibration import ResourceCaps, compile_locked_plan
from .design_sensitivity import (
    DesignSensitivityReport,
    SensitivityScenario,
    build_sensitivity_report,
)
from .identity import CanonicalModel, Sha256Digest, require_nonempty
from .paired_analysis import PairedExperimentSchedule


DECISION_SCOPE = "PHASE3D6_EXPERIMENT_DESIGN_DECISION"


class DesignDecisionError(ValueError):
    """An experiment-design decision is incomplete or violates preregistration."""


@dataclass(frozen=True, slots=True)
class DesignSelection(CanonicalModel):
    scenario_id: str
    resource_caps: ResourceCaps
    decision_reference: str

    def __post_init__(self) -> None:
        require_nonempty(self.scenario_id, "scenario_id")
        require_nonempty(self.decision_reference, "decision_reference")
        if not isinstance(self.resource_caps, ResourceCaps):
            raise TypeError("resource_caps must be ResourceCaps")


@dataclass(frozen=True, slots=True)
class DesignDecisionPackage(CanonicalModel):
    scope: str
    selected_scenario_id: str
    decision_reference: str
    selected_assumptions_digest: Sha256Digest
    scenario_set_digest: Sha256Digest
    sensitivity_report_digest: Sha256Digest
    input_plan_digest: Sha256Digest
    candidate_plan_digest: Sha256Digest
    task_count: int
    repeat_count_per_task: int
    total_pair_count: int
    total_arm_runs: int
    aggregate_total_model_token_ceiling: int
    aggregate_input_token_ceiling: int
    aggregate_output_token_ceiling: int
    aggregate_request_ceiling: int
    aggregate_arm_wall_time_budget_seconds: int
    aggregate_patch_byte_ceiling: int
    outcome_data_used: bool = False
    paid_model_called: bool = False
    automatic_scenario_selection: bool = False

    def __post_init__(self) -> None:
        if self.scope != DECISION_SCOPE:
            raise DesignDecisionError("unexpected design decision scope")
        require_nonempty(self.selected_scenario_id, "selected_scenario_id")
        require_nonempty(self.decision_reference, "decision_reference")
        for name in (
            "selected_assumptions_digest",
            "scenario_set_digest",
            "sensitivity_report_digest",
            "input_plan_digest",
            "candidate_plan_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, Sha256Digest):
                object.__setattr__(self, name, Sha256Digest(str(value)))
        for name in (
            "task_count",
            "repeat_count_per_task",
            "total_pair_count",
            "total_arm_runs",
            "aggregate_total_model_token_ceiling",
            "aggregate_input_token_ceiling",
            "aggregate_output_token_ceiling",
            "aggregate_request_ceiling",
            "aggregate_arm_wall_time_budget_seconds",
            "aggregate_patch_byte_ceiling",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise DesignDecisionError(f"{name} must be a positive integer")
        if self.total_arm_runs != self.total_pair_count * 2:
            raise DesignDecisionError("total_arm_runs must equal two arms per pair")
        if self.outcome_data_used or self.paid_model_called or self.automatic_scenario_selection:
            raise DesignDecisionError("Phase 3D6 decision evidence must remain outcome-blind and manual")


@dataclass(frozen=True, slots=True)
class BoundDesignDecisionEvidence(CanonicalModel):
    decision: DesignDecisionPackage
    schedule_identity: Sha256Digest
    schedule_pair_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.decision, DesignDecisionPackage):
            raise TypeError("decision must be DesignDecisionPackage")
        if not isinstance(self.schedule_identity, Sha256Digest):
            object.__setattr__(self, "schedule_identity", Sha256Digest(str(self.schedule_identity)))
        if isinstance(self.schedule_pair_count, bool) or not isinstance(self.schedule_pair_count, int):
            raise DesignDecisionError("schedule_pair_count must be an integer")
        if self.schedule_pair_count != self.decision.total_pair_count:
            raise DesignDecisionError("schedule pair count differs from selected design")


def prepare_design_decision(
    plan: Mapping[str, object],
    *,
    scenarios: Iterable[SensitivityScenario],
    selection: DesignSelection,
) -> tuple[dict[str, object], DesignSensitivityReport, DesignDecisionPackage]:
    """Bind one explicit scenario and explicit caps to a LOCKED-plan candidate."""
    if not isinstance(selection, DesignSelection):
        raise TypeError("selection must be DesignSelection")
    values = tuple(scenarios)
    if not values:
        raise DesignDecisionError("design decision requires at least one predeclared scenario")

    matches = [item for item in values if item.scenario_id == selection.scenario_id]
    if len(matches) != 1:
        raise DesignDecisionError("selected scenario_id must identify exactly one predeclared scenario")
    selected = matches[0]

    corpus = plan.get("corpus")
    tasks = corpus.get("tasks") if isinstance(corpus, Mapping) else None
    if not isinstance(tasks, list) or not tasks or any(not isinstance(item, str) for item in tasks):
        raise DesignDecisionError("experiment plan has no valid task cohort")

    report = build_sensitivity_report(task_count=len(tasks), scenarios=values)
    selected_rows = [row for row in report.rows if row.scenario_id == selection.scenario_id]
    if len(selected_rows) != 1:
        raise DesignDecisionError("selected scenario is absent from the sensitivity report")
    selected_row = selected_rows[0]
    if not selected_row.reachable or selected_row.repeat_count_per_task is None:
        raise DesignDecisionError("selected scenario cannot reach target power within its declared bound")

    candidate = compile_locked_plan(
        plan,
        assumptions=selected.assumptions,
        caps=selection.resource_caps,
    )
    execution = candidate.get("execution")
    stopping = candidate.get("stopping")
    if not isinstance(execution, Mapping) or not isinstance(stopping, Mapping):
        raise DesignDecisionError("compiled plan is missing execution/stopping objects")
    repeat_count = execution.get("repeat_count_per_task")
    pair_count = stopping.get("required_completed_pairs")
    if repeat_count != selected_row.repeat_count_per_task or pair_count != selected_row.total_pair_count:
        raise DesignDecisionError("compiled plan differs from the explicitly selected sensitivity row")
    if not isinstance(repeat_count, int) or not isinstance(pair_count, int):
        raise DesignDecisionError("compiled design counts must be integers")

    arm_runs = pair_count * 2
    caps = selection.resource_caps
    decision = DesignDecisionPackage(
        scope=DECISION_SCOPE,
        selected_scenario_id=selection.scenario_id,
        decision_reference=selection.decision_reference,
        selected_assumptions_digest=selected.assumptions.content_digest,
        scenario_set_digest=Sha256Digest.of(values),
        sensitivity_report_digest=report.content_digest,
        input_plan_digest=Sha256Digest.of(plan),
        candidate_plan_digest=Sha256Digest.of(candidate),
        task_count=len(tasks),
        repeat_count_per_task=repeat_count,
        total_pair_count=pair_count,
        total_arm_runs=arm_runs,
        aggregate_total_model_token_ceiling=arm_runs * caps.total_model_token_cap_per_arm,
        aggregate_input_token_ceiling=arm_runs * caps.input_token_cap_per_arm,
        aggregate_output_token_ceiling=arm_runs * caps.output_token_cap_per_arm,
        aggregate_request_ceiling=arm_runs * caps.max_requests_per_arm,
        aggregate_arm_wall_time_budget_seconds=arm_runs * caps.wall_time_seconds_per_arm,
        aggregate_patch_byte_ceiling=arm_runs * caps.patch_byte_cap_per_arm,
    )
    return candidate, report, decision


def bind_decision_to_schedule(
    decision: DesignDecisionPackage,
    schedule: PairedExperimentSchedule,
) -> BoundDesignDecisionEvidence:
    """Bind reviewed decision evidence to the exact generated immutable schedule."""
    if not isinstance(decision, DesignDecisionPackage):
        raise TypeError("decision must be DesignDecisionPackage")
    if not isinstance(schedule, PairedExperimentSchedule):
        raise TypeError("schedule must be PairedExperimentSchedule")
    if schedule.design_identity != decision.candidate_plan_digest:
        raise DesignDecisionError("schedule was generated from a different locked-plan candidate")
    return BoundDesignDecisionEvidence(
        decision=decision,
        schedule_identity=schedule.content_digest,
        schedule_pair_count=len(schedule.entries),
    )
