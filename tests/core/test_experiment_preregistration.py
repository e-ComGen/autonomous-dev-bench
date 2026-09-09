from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from benchmark_core.experiment_preregistration import (
    ExperimentDesignSnapshot,
    ExperimentPlanInvalid,
)
from benchmark_core.paired_analysis import PairedExperimentSchedule


ROOT = Path(__file__).resolve().parents[2]
SUPPORT_SOURCES = (
    "DEEPSEEK_HARNESS.lock.json",
    "ADCP.lock.json",
    "HARBOR.lock.json",
    "migration/swebench_v5_verified_parity.json",
)


def _copy_design_sources(tmp_path: Path) -> None:
    shutil.copyfile(
        ROOT / "PHASE3D_EXPERIMENT_PLAN.prelock.json",
        tmp_path / "PHASE3D_EXPERIMENT_PLAN.json",
    )
    for relative in SUPPORT_SOURCES:
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


def _make_ready(plan: dict[str, object], *, repeats: int = 2) -> None:
    plan["status"] = "LOCKED"
    plan["execution"]["repeat_count_per_task"] = repeats
    plan["budget"].update(
        total_model_token_cap_per_arm=120000,
        input_token_cap_per_arm=100000,
        output_token_cap_per_arm=50000,
        max_requests_per_arm=64,
        wall_time_seconds_per_arm=3600,
        patch_byte_cap_per_arm=1000000,
    )
    plan["stopping"]["required_completed_pairs"] = 10 * repeats
    plan["design_paid_ready"] = True
    plan["design_blockers"] = []


def test_current_repository_design_is_locked_and_compiles_exact_schedule() -> None:
    snapshot = ExperimentDesignSnapshot.from_repository(ROOT)

    assert snapshot.design_paid_ready is True
    assert len(snapshot.task_ids) == 10
    assert snapshot.task_ids[0] == "astropy__astropy-12907"
    assert snapshot.task_ids[-1] == "sympy__sympy-20590"
    assert snapshot.repeat_count_per_task == 37
    assert snapshot.required_completed_pairs == 370
    assert snapshot.total_model_token_cap_per_arm == 262144
    assert snapshot.input_token_cap_per_arm == 262144
    assert snapshot.output_token_cap_per_arm == 65536
    assert snapshot.max_requests_per_arm == 16
    assert snapshot.wall_time_seconds_per_arm == 600
    assert snapshot.patch_byte_cap_per_arm == 262144
    assert snapshot.design_blockers == ()
    assert snapshot.expected_pair_id("psf__requests-1142", 0) == "phase3d-psf__requests-1142-r0"
    assert snapshot.expected_seed("psf__requests-1142", 0) != snapshot.expected_seed("psf__requests-1142", 1)

    schedule = PairedExperimentSchedule.from_design(snapshot)
    assert len(schedule.entries) == 370
    assert schedule.design_identity == snapshot.plan_digest
    assert schedule.entries[0].pair_id == "phase3d-astropy__astropy-12907-r0"
    assert schedule.entries[-1].pair_id == "phase3d-sympy__sympy-20590-r36"


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


def test_analysis_alpha_drift_is_hard_invalid(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["analysis"]["alpha"] = 0.10
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="analysis.alpha"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_analysis_test_drift_is_hard_invalid(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["analysis"]["inferential_test"] = "posthoc_test"
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="analysis.inferential_test"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_incomplete_schedule_requirement_cannot_be_disabled(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    plan["analysis"]["final_analysis_requires_complete_schedule"] = False
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="final_analysis_requires_complete_schedule"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_fully_precommitted_design_can_become_design_ready_and_compile_exact_schedule(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    _make_ready(plan)
    _write_plan(tmp_path, plan)

    snapshot = ExperimentDesignSnapshot.from_repository(tmp_path)
    assert snapshot.design_paid_ready is True
    assert snapshot.design_blockers == ()
    assert snapshot.repeat_count_per_task == 2
    assert snapshot.required_completed_pairs == 20
    assert snapshot.total_model_token_cap_per_arm == 120000
    assert snapshot.input_token_cap_per_arm == 100000
    assert snapshot.output_token_cap_per_arm == 50000
    assert snapshot.max_requests_per_arm == 64
    assert snapshot.wall_time_seconds_per_arm == 3600
    assert snapshot.patch_byte_cap_per_arm == 1000000
    assert 0 <= snapshot.expected_seed("psf__requests-1142", 1) < 2**64

    schedule = PairedExperimentSchedule.from_design(snapshot)
    assert len(schedule.entries) == 20
    assert schedule.design_identity == snapshot.plan_digest
    assert schedule.entries[0].pair_id == "phase3d-astropy__astropy-12907-r0"
    assert schedule.entries[1].pair_id == "phase3d-astropy__astropy-12907-r1"
    assert schedule.entries[-1].pair_id == "phase3d-sympy__sympy-20590-r1"
    assert schedule.entries[0].seed == snapshot.expected_seed("astropy__astropy-12907", 0)


def test_stopping_count_must_equal_task_count_times_repeats(tmp_path: Path) -> None:
    _copy_design_sources(tmp_path)
    plan = _plan(tmp_path)
    _make_ready(plan)
    plan["stopping"]["required_completed_pairs"] = 19
    _write_plan(tmp_path, plan)

    with pytest.raises(ExperimentPlanInvalid, match="task_count \* repeat_count"):
        ExperimentDesignSnapshot.from_repository(tmp_path)


def test_pair_seed_rejects_task_outside_fixed_cohort() -> None:
    snapshot = ExperimentDesignSnapshot.from_repository(ROOT)

    with pytest.raises(ExperimentPlanInvalid, match="outside the preregistered cohort"):
        snapshot.expected_seed("not__in-cohort-1", 0)
