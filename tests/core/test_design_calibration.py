from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from benchmark_core.design_calibration import (
    CALIBRATION_METHOD,
    CalibrationAssumptions,
    DesignCalibrationError,
    DesignPowerUnavailable,
    ResourceCaps,
    calibrate_repeat_count,
    compile_locked_plan,
    exact_paired_power,
)
from benchmark_core.experiment_preregistration import ExperimentDesignSnapshot


ROOT = Path(__file__).resolve().parents[2]


def assumptions(**overrides) -> CalibrationAssumptions:
    values = {
        "expected_discordant_rate": 1.0,
        "adcp_win_probability_given_discordance": 1.0,
        "target_power": 0.8,
        "max_repeat_count": 10,
        "assumption_source": "budget_sensitivity_scenario",
        "assumption_reference": "qualification-fixture-no-outcomes",
    }
    values.update(overrides)
    return CalibrationAssumptions(**values)


def caps(**overrides) -> ResourceCaps:
    values = {
        "total_model_token_cap_per_arm": 1000,
        "input_token_cap_per_arm": 800,
        "output_token_cap_per_arm": 500,
        "max_requests_per_arm": 10,
        "wall_time_seconds_per_arm": 600,
        "patch_byte_cap_per_arm": 100000,
    }
    values.update(overrides)
    return ResourceCaps(**values)


def load_plan() -> dict[str, object]:
    return json.loads((ROOT / "PHASE3D_EXPERIMENT_PLAN.json").read_text(encoding="utf-8"))


def test_exact_power_matches_known_mcnemar_boundary() -> None:
    a = assumptions()
    assert exact_paired_power(5, a) == pytest.approx(0.0)
    assert exact_paired_power(6, a) == pytest.approx(1.0)


def test_repeat_calibration_respects_equal_per_task_schedule() -> None:
    result = calibrate_repeat_count(task_count=2, assumptions=assumptions(max_repeat_count=5))

    assert result.repeat_count_per_task == 3
    assert result.total_pair_count == 6
    assert result.achieved_power == pytest.approx(1.0)
    assert result.expected_discordant_pairs == pytest.approx(6.0)
    assert result.implied_resolution_rate_difference == pytest.approx(1.0)
    assert result.method == CALIBRATION_METHOD


def test_power_search_fails_closed_when_bound_cannot_reach_target() -> None:
    with pytest.raises(DesignPowerUnavailable, match="not reachable"):
        calibrate_repeat_count(
            task_count=1,
            assumptions=assumptions(max_repeat_count=5),
        )


def test_null_effect_assumption_is_rejected() -> None:
    with pytest.raises(DesignCalibrationError, match="null value"):
        assumptions(adcp_win_probability_given_discordance=0.5)


def test_outcome_derived_assumption_source_is_not_allowed() -> None:
    with pytest.raises(DesignCalibrationError, match="pre-experiment"):
        assumptions(assumption_source="paid_experiment_outcomes")


def test_resource_caps_must_fit_inside_primary_total_budget() -> None:
    with pytest.raises(DesignCalibrationError, match="input token cap"):
        caps(total_model_token_cap_per_arm=100, input_token_cap_per_arm=101)
    with pytest.raises(DesignCalibrationError, match="output token cap"):
        caps(total_model_token_cap_per_arm=100, output_token_cap_per_arm=101)


def test_compiler_refuses_to_overwrite_any_existing_design_choice() -> None:
    plan = load_plan()
    plan["execution"]["repeat_count_per_task"] = 2

    with pytest.raises(DesignCalibrationError, match="already set"):
        compile_locked_plan(plan, assumptions=assumptions(), caps=caps())


def test_compiler_refuses_post_outcome_plan() -> None:
    plan = load_plan()
    plan["winner"] = "ADCP"

    with pytest.raises(DesignCalibrationError, match="outcomes"):
        compile_locked_plan(plan, assumptions=assumptions(), caps=caps())


def test_compiled_locked_plan_is_accepted_by_existing_preregistration_validator(tmp_path: Path) -> None:
    plan = load_plan()
    locked = compile_locked_plan(
        plan,
        assumptions=assumptions(
            expected_discordant_rate=1.0,
            adcp_win_probability_given_discordance=1.0,
            target_power=0.8,
            max_repeat_count=3,
            assumption_reference="deterministic-validator-fixture",
        ),
        caps=caps(),
    )

    # Ten accepted tasks and exact McNemar p<0.05 with a fully directional
    # discordance scenario require only one repeat (10 total pairs).
    assert locked["status"] == "LOCKED"
    assert locked["design_paid_ready"] is True
    assert locked["design_blockers"] == []
    assert locked["execution"]["repeat_count_per_task"] == 1
    assert locked["stopping"]["required_completed_pairs"] == 10
    assert locked["calibration"]["outcome_data_used"] is False
    assert locked["calibration"]["paid_model_called"] is False

    (tmp_path / "migration").mkdir()
    for name in (
        "DEEPSEEK_HARNESS.lock.json",
        "ADCP.lock.json",
        "HARBOR.lock.json",
    ):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copyfile(
        ROOT / "migration" / "swebench_v5_verified_parity.json",
        tmp_path / "migration" / "swebench_v5_verified_parity.json",
    )
    (tmp_path / "PHASE3D_EXPERIMENT_PLAN.json").write_text(
        json.dumps(locked, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    snapshot = ExperimentDesignSnapshot.from_repository(tmp_path)
    assert snapshot.status == "LOCKED"
    assert snapshot.design_paid_ready is True
    assert snapshot.repeat_count_per_task == 1
    assert snapshot.required_completed_pairs == 10
    assert snapshot.total_model_token_cap_per_arm == 1000


def test_power_is_symmetric_for_equal_distance_from_null() -> None:
    common = {
        "expected_discordant_rate": 0.7,
        "target_power": 0.8,
        "max_repeat_count": 20,
        "assumption_source": "external_prior",
        "assumption_reference": "symmetry-test",
    }
    high = CalibrationAssumptions(adcp_win_probability_given_discordance=0.7, **common)
    low = CalibrationAssumptions(adcp_win_probability_given_discordance=0.3, **common)

    assert exact_paired_power(30, high) == pytest.approx(exact_paired_power(30, low), abs=1e-14)
