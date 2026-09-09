from __future__ import annotations

import pytest

from benchmark_core.design_calibration import CalibrationAssumptions
from benchmark_core.design_sensitivity import (
    DesignSensitivityError,
    SensitivityScenario,
    build_sensitivity_report,
)


def scenario(
    scenario_id: str,
    *,
    q: float,
    p: float,
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
            assumption_reference=f"fixture:{scenario_id}",
        ),
    )


def test_report_preserves_explicit_scenario_order_and_never_selects_one() -> None:
    report = build_sensitivity_report(
        task_count=10,
        scenarios=(
            scenario("strong", q=1.0, p=1.0),
            scenario("moderate", q=0.7, p=0.7, max_repeat_count=20),
        ),
    )

    assert [row.scenario_id for row in report.rows] == ["strong", "moderate"]
    assert report.automatic_scenario_selection is False
    assert report.outcome_data_used is False
    assert report.paid_model_called is False
    assert report.rows[0].reachable is True
    assert report.rows[0].repeat_count_per_task == 1
    assert report.rows[0].total_pair_count == 10
    assert report.rows[0].total_arm_runs == 20


def test_unreachable_scenario_is_reported_not_dropped() -> None:
    report = build_sensitivity_report(
        task_count=1,
        scenarios=(scenario("too-small", q=1.0, p=1.0, max_repeat_count=5),),
    )

    row = report.rows[0]
    assert row.reachable is False
    assert row.repeat_count_per_task is None
    assert row.total_pair_count is None
    assert row.total_arm_runs is None
    assert row.achieved_power == pytest.approx(0.0)
    assert row.target_power == pytest.approx(0.8)


def test_duplicate_scenario_ids_fail_closed() -> None:
    duplicate = scenario("same", q=1.0, p=1.0)
    with pytest.raises(DesignSensitivityError, match="unique"):
        build_sensitivity_report(task_count=10, scenarios=(duplicate, duplicate))


def test_report_is_deterministic_for_same_inputs() -> None:
    scenarios = (
        scenario("a", q=0.8, p=0.8, max_repeat_count=20),
        scenario("b", q=0.6, p=0.7, max_repeat_count=30),
    )
    first = build_sensitivity_report(task_count=10, scenarios=scenarios)
    second = build_sensitivity_report(task_count=10, scenarios=scenarios)

    assert first.to_canonical_json() == second.to_canonical_json()
    assert first.content_digest == second.content_digest


def test_scenario_requires_calibration_assumptions() -> None:
    with pytest.raises(TypeError, match="CalibrationAssumptions"):
        SensitivityScenario(scenario_id="bad", assumptions=object())  # type: ignore[arg-type]
