from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from benchmark_core.experiment_preregistration import (
    ExperimentDesignSnapshot,
    ExperimentPlanInvalid,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "PHASE3D_EXPERIMENT_PLAN.json",
    "DEEPSEEK_HARNESS.lock.json",
    "ADCP.lock.json",
    "HARBOR.lock.json",
    "migration/swebench_v5_verified_parity.json",
)


def _copy_design_sources(tmp_path: Path) -> None:
    for relative in SOURCES:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _plan(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "PHASE3D_EXPERIMENT_PLAN.json").read_text(encoding="utf-8"))


def _write_plan(tmp_path: Path, plan: dict[str, object]) -> None:
    (tmp_path / "PHASE3D_EXPERIMENT_PLAN.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_current_repository_design_is_structurally_valid_but_cost_and_repeat_blocked() -> None:
    snapshot = ExperimentDesignSnapshot.from_repository(ROOT)

    assert snapshot.design_paid_ready is False
    assert snapshot.task_count == 10
    assert snapshot.repeat_count_per_task is None
    assert snapshot.required_completed_pairs is None
    assert snapshot.total_model_token_cap_per_arm is None
    assert snapshot.design_blockers == (
        "EXPERIMENT_PLAN_NOT_LOCKED",
        "REPEAT_COUNT_NOT_PRECOMMITTED",
        "PRIMARY_TOKEN_BUDGET_NOT_PRECOMMITTED",
        "SECONDARY_RESOURCE_LIMITS_NOT_PRECOMMITTED",
    )


def test_corpus_drift_is_invalid_not_a_soft_blocker(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["corpus"]["tasks"] = plan["corpus"]["tasks"][:-1]
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="task cohort"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_treatment_commit_drift_is_invalid(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["treatment"]["arm_b"]["commit"] = "0" * 40
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="Arm B commit"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_fully_precommitted_design_can_become_design_ready(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["status"] = "LOCKED"
    plan["execution"]["repeat_count_per_task"] = 2
    plan["budget"].update(
        total_model_token_cap_per_arm=120000,
        input_token_cap_per_arm=100000,
        output_token_cap_per_arm=50000,
        max_requests_per_arm=64,
        wall_time_seconds_per_arm=3600,
        patch_byte_cap_per_arm=1000000,
    )
    plan["stopping"]["required_completed_pairs"] = 20
    plan["design_paid_ready"] = True
    plan["design_blockers"] = []
    _write_plan(tmp_path, plan)

    snapshot = ExperimentDesignSnapshot.from_repository(tmp_path)
    assert snapshot.design_paid_ready is True
    assert snapshot.design_blockers == ()
    assert snapshot.repeat_count_per_task == 2
    assert snapshot.required_completed_pairs == 20
    assert snapshot.total_model_token_cap_per_arm == 120000


def test_stopping_count_must_equal_task_count_times_repeats(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["status"] = "LOCKED"
    plan["execution"]["repeat_count_per_task"] = 2
    plan["budget"].update(
        total_model_token_cap_per_arm=120000,
        input_token_cap_per_arm=100000,
        output_token_cap_per_arm=50000,
        max_requests_per_arm=64,
        wall_time_seconds_per_arm=3600,
        patch_byte_cap_per_arm=1000000,
    )
    plan["stopping"]["required_completed_pairs"] = 19
    plan["design_paid_ready"] = True
    plan["design_blockers"] = []
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="task_count \* repeat_count"):
        ExperimentDesignSnapshot.from_repository(tmp_path)
