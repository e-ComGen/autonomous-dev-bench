from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_core.design_calibration import CalibrationAssumptions, ResourceCaps
from benchmark_core.design_decision import (
    DECISION_SCOPE,
    DesignDecisionError,
    DesignSelection,
    bind_decision_to_schedule,
    prepare_design_decision,
)
from benchmark_core.design_sensitivity import SensitivityScenario
from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_analysis import PairScheduleEntry, PairedExperimentSchedule


ROOT = Path(__file__).resolve().parents[2]


def load_plan() -> dict[str, object]:
    return json.loads((ROOT / "PHASE3D_EXPERIMENT_PLAN.json").read_text(encoding="utf-8"))


def scenario(
    scenario_id: str,
    *,
    q: float = 1.0,
    p: float = 1.0,
    power: float = 0.8,
    max_repeat_count: int = 10,
) -> SensitivityScenario:
    return SensitivityScenario(
        scenario_id=scenario_id,
        assumptions=CalibrationAssumptions(
            expected_discordant_rate=q,
            adcp_win_probability_given_discordance=p,
            target_power=power,
            max_repeat_count=max_repeat_count,
            assumption_source="budget_sensitivity_scenario",
            assumption_reference=f"phase3d6-fixture:{scenario_id}",
        ),
    )


def caps() -> ResourceCaps:
    return ResourceCaps(
        total_model_token_cap_per_arm=1000,
        input_token_cap_per_arm=800,
        output_token_cap_per_arm=500,
        max_requests_per_arm=10,
        wall_time_seconds_per_arm=600,
        patch_byte_cap_per_arm=100000,
    )


def selection(scenario_id: str) -> DesignSelection:
    return DesignSelection(
        scenario_id=scenario_id,
        resource_caps=caps(),
        decision_reference="operator-review:phase3d6-fixture",
    )


def test_decision_binds_only_explicitly_selected_predeclared_scenario() -> None:
    plan = load_plan()
    scenarios = (
        scenario("selected"),
        scenario("alternate", q=0.7, p=0.8, max_repeat_count=20),
    )

    candidate, report, decision = prepare_design_decision(
        plan,
        scenarios=scenarios,
        selection=selection("selected"),
    )

    assert decision.scope == DECISION_SCOPE
    assert decision.selected_scenario_id == "selected"
    assert decision.selected_assumptions_digest == scenarios[0].assumptions.content_digest
    assert decision.sensitivity_report_digest == report.content_digest
    assert decision.input_plan_digest == Sha256Digest.of(plan)
    assert decision.candidate_plan_digest == Sha256Digest.of(candidate)
    assert decision.repeat_count_per_task == 1
    assert decision.total_pair_count == 10
    assert decision.total_arm_runs == 20
    assert decision.aggregate_total_model_token_ceiling == 20000
    assert decision.aggregate_input_token_ceiling == 16000
    assert decision.aggregate_output_token_ceiling == 10000
    assert decision.aggregate_request_ceiling == 200
    assert decision.aggregate_arm_wall_time_budget_seconds == 12000
    assert decision.aggregate_patch_byte_ceiling == 2000000
    assert decision.automatic_scenario_selection is False
    assert decision.outcome_data_used is False
    assert decision.paid_model_called is False
    assert candidate["status"] == "LOCKED"
    assert candidate["execution"]["repeat_count_per_task"] == 1
    assert candidate["stopping"]["required_completed_pairs"] == 10


def test_missing_selected_scenario_fails_closed_instead_of_auto_selecting() -> None:
    with pytest.raises(DesignDecisionError, match="exactly one"):
        prepare_design_decision(
            load_plan(),
            scenarios=(scenario("a"), scenario("b")),
            selection=selection("missing"),
        )


def test_unreachable_selected_scenario_fails_closed() -> None:
    unreachable = scenario(
        "unreachable",
        q=0.1,
        p=0.6,
        power=0.99,
        max_repeat_count=1,
    )
    with pytest.raises(DesignDecisionError, match="cannot reach target power"):
        prepare_design_decision(
            load_plan(),
            scenarios=(unreachable,),
            selection=selection("unreachable"),
        )


def test_decision_does_not_accept_post_outcome_plan() -> None:
    plan = load_plan()
    plan["winner"] = "ADCP"
    with pytest.raises(ValueError, match="outcomes"):
        prepare_design_decision(
            plan,
            scenarios=(scenario("selected"),),
            selection=selection("selected"),
        )


def test_schedule_binding_requires_candidate_plan_identity_and_exact_pair_count() -> None:
    _, _, decision = prepare_design_decision(
        load_plan(),
        scenarios=(scenario("selected"),),
        selection=selection("selected"),
    )
    entries = tuple(
        PairScheduleEntry(
            pair_id=f"phase3d-task-{index}-r0",
            task_id=f"task-{index}",
            repeat_index=0,
            seed=1000 + index,
        )
        for index in range(decision.total_pair_count)
    )
    schedule = PairedExperimentSchedule(
        design_identity=decision.candidate_plan_digest,
        entries=entries,
    )

    evidence = bind_decision_to_schedule(decision, schedule)
    assert evidence.schedule_identity == schedule.content_digest
    assert evidence.schedule_pair_count == decision.total_pair_count

    foreign_schedule = PairedExperimentSchedule(
        design_identity=Sha256Digest("sha256:" + "f" * 64),
        entries=entries,
    )
    with pytest.raises(DesignDecisionError, match="different locked-plan candidate"):
        bind_decision_to_schedule(decision, foreign_schedule)


def test_schedule_binding_rejects_pair_count_drift() -> None:
    _, _, decision = prepare_design_decision(
        load_plan(),
        scenarios=(scenario("selected"),),
        selection=selection("selected"),
    )
    schedule = PairedExperimentSchedule(
        design_identity=decision.candidate_plan_digest,
        entries=(
            PairScheduleEntry(
                pair_id="phase3d-one-r0",
                task_id="one",
                repeat_index=0,
                seed=1,
            ),
        ),
    )
    with pytest.raises(DesignDecisionError, match="schedule pair count"):
        bind_decision_to_schedule(decision, schedule)
