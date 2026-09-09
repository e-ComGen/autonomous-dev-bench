"""Outcome-blind sensitivity analysis for Phase 3D design choices.

Sensitivity reports compare explicit pre-experiment assumption scenarios without
selecting a winner scenario and without inspecting paid experiment outcomes. The
purpose is to make the consequence of assumptions visible before a human locks
repeat count and resource budgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .design_calibration import (
    CalibrationAssumptions,
    CalibrationResult,
    DesignPowerUnavailable,
    calibrate_repeat_count,
    exact_paired_power,
)
from .identity import CanonicalModel


class DesignSensitivityError(ValueError):
    """A sensitivity scenario set is invalid."""


@dataclass(frozen=True, slots=True)
class SensitivityScenario(CanonicalModel):
    scenario_id: str
    assumptions: CalibrationAssumptions

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise DesignSensitivityError("scenario_id must be non-empty")
        if not isinstance(self.assumptions, CalibrationAssumptions):
            raise TypeError("assumptions must be CalibrationAssumptions")


@dataclass(frozen=True, slots=True)
class SensitivityRow(CanonicalModel):
    scenario_id: str
    reachable: bool
    repeat_count_per_task: int | None
    total_pair_count: int | None
    total_arm_runs: int | None
    achieved_power: float
    target_power: float
    expected_discordant_pairs: float | None
    implied_resolution_rate_difference: float
    max_repeat_count: int
    assumptions_digest: str


@dataclass(frozen=True, slots=True)
class DesignSensitivityReport(CanonicalModel):
    task_count: int
    rows: tuple[SensitivityRow, ...]
    outcome_data_used: bool = False
    paid_model_called: bool = False
    automatic_scenario_selection: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.task_count, bool) or not isinstance(self.task_count, int) or self.task_count <= 0:
            raise DesignSensitivityError("task_count must be a positive integer")
        rows = tuple(self.rows)
        if not rows:
            raise DesignSensitivityError("sensitivity report requires at least one scenario")
        if len({row.scenario_id for row in rows}) != len(rows):
            raise DesignSensitivityError("sensitivity report contains duplicate scenario ids")
        object.__setattr__(self, "rows", rows)


def build_sensitivity_report(
    *,
    task_count: int,
    scenarios: Iterable[SensitivityScenario],
) -> DesignSensitivityReport:
    """Evaluate each explicit scenario independently; never choose among them."""
    if isinstance(task_count, bool) or not isinstance(task_count, int) or task_count <= 0:
        raise DesignSensitivityError("task_count must be a positive integer")
    values = tuple(scenarios)
    if not values:
        raise DesignSensitivityError("at least one scenario is required")
    if len({item.scenario_id for item in values}) != len(values):
        raise DesignSensitivityError("scenario_id values must be unique")

    rows = tuple(_evaluate_scenario(task_count, scenario) for scenario in values)
    return DesignSensitivityReport(task_count=task_count, rows=rows)


def _evaluate_scenario(task_count: int, scenario: SensitivityScenario) -> SensitivityRow:
    assumptions = scenario.assumptions
    implied_effect = assumptions.expected_discordant_rate * (
        2.0 * assumptions.adcp_win_probability_given_discordance - 1.0
    )
    try:
        result: CalibrationResult = calibrate_repeat_count(
            task_count=task_count,
            assumptions=assumptions,
        )
    except DesignPowerUnavailable:
        max_pairs = task_count * assumptions.max_repeat_count
        return SensitivityRow(
            scenario_id=scenario.scenario_id,
            reachable=False,
            repeat_count_per_task=None,
            total_pair_count=None,
            total_arm_runs=None,
            achieved_power=exact_paired_power(max_pairs, assumptions),
            target_power=assumptions.target_power,
            expected_discordant_pairs=None,
            implied_resolution_rate_difference=implied_effect,
            max_repeat_count=assumptions.max_repeat_count,
            assumptions_digest=str(assumptions.content_digest),
        )

    return SensitivityRow(
        scenario_id=scenario.scenario_id,
        reachable=True,
        repeat_count_per_task=result.repeat_count_per_task,
        total_pair_count=result.total_pair_count,
        total_arm_runs=result.total_pair_count * 2,
        achieved_power=result.achieved_power,
        target_power=result.target_power,
        expected_discordant_pairs=result.expected_discordant_pairs,
        implied_resolution_rate_difference=result.implied_resolution_rate_difference,
        max_repeat_count=assumptions.max_repeat_count,
        assumptions_digest=str(assumptions.content_digest),
    )
