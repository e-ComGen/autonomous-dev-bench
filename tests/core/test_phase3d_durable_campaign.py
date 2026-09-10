from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark_core.paired_analysis import ExclusionReason, PairedExperimentSchedule
from benchmark_core.paired_experiment import ArmExecutionReceipt, ExperimentArm, PaidAdmissionSnapshot, PaidExperimentBlocked
from benchmark_core.phase3d_campaign import (
    CampaignArmArtifact,
    CampaignRecoveryRequired,
    DurablePhase3DCampaign,
    OfficialGradeArtifact,
    PaidCampaignAuthorizationRequired,
    Phase3DCampaignError,
    _atomic_write_json,
    materialize_pair_plan,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIGEST = "sha256:" + "a" * 64


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ExperimentArm]] = []

    def execute_arm(self, plan, arm, attempt_dir):
        self.calls.append((plan.pair_id, arm))
        manifest = plan.manifest_for(arm)
        return CampaignArmArtifact(
            receipt=ArmExecutionReceipt(
                arm=arm,
                manifest_identity=manifest.identity,
                status="PASS",
                model_called=True,
                total_model_tokens=1,
                requests=1,
            ),
            patch_sha256=sha256_bytes(f"{plan.pair_id}:{arm.value}:patch".encode()),
            patch_bytes=1,
            evidence_sha256=sha256_bytes(f"{plan.pair_id}:{arm.value}:evidence".encode()),
        )


class RecordingGrader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ExperimentArm]] = []

    def grade_arm(self, plan, arm, artifact, attempt_dir):
        self.calls.append((plan.pair_id, arm))
        # Unit-test outcomes are deliberately synthetic; campaign public progress
        # must never expose them before the complete preregistered schedule.
        return OfficialGradeArtifact(
            resolved=arm is ExperimentArm.ADCP,
            evidence_sha256=sha256_bytes(f"{plan.pair_id}:{arm.value}:grade".encode()),
        )


class PreDispatchOnceExecutor(RecordingExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def execute_arm(self, plan, arm, attempt_dir):
        from benchmark_core.phase3d_campaign import PreDispatchInfrastructureFailure

        if not self.failed:
            self.failed = True
            raise PreDispatchInfrastructureFailure("fixture proved zero provider requests")
        return super().execute_arm(plan, arm, attempt_dir)


def _campaign(tmp_path: Path, *, admission: PaidAdmissionSnapshot | None = None, executor=None, grader=None):
    admission = admission or PaidAdmissionSnapshot.from_repository(ROOT)
    schedule = PairedExperimentSchedule.from_design(admission.experiment_design)
    executor = executor or RecordingExecutor()
    grader = grader or RecordingGrader()
    runner = DurablePhase3DCampaign(
        repository_root=ROOT,
        workspace=tmp_path / "campaign",
        expected_benchmark_commit="fixture-commit-check-is-monkeypatched",
        admission=admission,
        schedule=schedule,
        plan_factory=lambda entry: materialize_pair_plan(
            admission,
            entry,
            environment_image_digest=IMAGE_DIGEST,
        ),
        executor=executor,
        grader=grader,
    )
    return runner, schedule, executor, grader


def _skip_git_identity(monkeypatch) -> None:
    monkeypatch.setattr(DurablePhase3DCampaign, "_require_exact_repository_commit", lambda self: None)


def test_locked_schedule_materializes_exact_370_pair_identity() -> None:
    admission = PaidAdmissionSnapshot.from_repository(ROOT)
    schedule = PairedExperimentSchedule.from_design(admission.experiment_design)

    assert len(schedule.entries) == 370
    assert schedule.entries[0].pair_id == "phase3d-astropy__astropy-12907-r0"
    assert schedule.entries[0].seed == 7185244970315077519
    assert schedule.entries[-1].pair_id == "phase3d-sympy__sympy-20590-r36"
    assert schedule.entries[-1].seed == 14301790471053806025
    assert str(schedule.content_digest) == "sha256:05c43a35e67f2f2b1a00346785ded3c5e3ff51370f2bda952340c490470b298b"


def test_authorization_absent_cannot_invoke_executor(tmp_path: Path) -> None:
    runner, _schedule, executor, grader = _campaign(tmp_path)

    with pytest.raises(PaidCampaignAuthorizationRequired):
        runner.run(paid_authorized=False, max_new_pairs=1)

    assert executor.calls == []
    assert grader.calls == []


def test_blocked_paid_admission_cannot_invoke_executor(tmp_path: Path, monkeypatch) -> None:
    admission = replace(PaidAdmissionSnapshot.from_repository(ROOT), adcp_paid_ready=False)
    runner, _schedule, executor, grader = _campaign(tmp_path, admission=admission)
    _skip_git_identity(monkeypatch)

    with pytest.raises(PaidExperimentBlocked):
        runner.run(paid_authorized=True, max_new_pairs=1)

    assert executor.calls == []
    assert grader.calls == []


def test_one_pair_commits_atomically_and_resume_skips_it(tmp_path: Path, monkeypatch) -> None:
    runner, schedule, executor, grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)

    first = runner.run(paid_authorized=True, max_new_pairs=1)
    assert first.completed_pairs == 1
    assert first.excluded_attempts == 0
    assert len(executor.calls) == 2
    assert [arm for _, arm in executor.calls] == list(
        materialize_pair_plan(
            runner.admission,
            schedule.entries[0],
            environment_image_digest=IMAGE_DIGEST,
        ).arm_order
    )
    first_pair = schedule.entries[0].pair_id
    assert {pair for pair, _ in executor.calls} == {first_pair}

    second = runner.run(paid_authorized=True, max_new_pairs=1)
    assert second.completed_pairs == 2
    assert len(executor.calls) == 4
    assert [pair for pair, _ in executor.calls].count(first_pair) == 2
    assert {pair for pair, _ in executor.calls[-2:]} == {schedule.entries[1].pair_id}
    assert len(grader.calls) == 4


def test_resume_after_durable_first_arm_runs_only_missing_second_arm(tmp_path: Path, monkeypatch) -> None:
    runner, schedule, executor, grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)
    runner._initialize_or_validate_campaign()

    entry = schedule.entries[0]
    plan = runner.plan_factory(entry)
    first_arm = plan.arm_order[0]
    first_manifest = plan.manifest_for(first_arm)
    attempt_dir = runner.pairs_root / entry.pair_id / "attempt-0000"
    attempt_dir.mkdir(parents=True)
    _atomic_write_json(
        attempt_dir / "attempt.json",
        {
            "schema_version": 1,
            "pair_id": entry.pair_id,
            "task_id": entry.task_id,
            "repeat_index": entry.repeat_index,
            "seed": entry.seed,
            "attempt_index": 0,
            "pair_identity": str(plan.pair_identity),
            "execution_order": [arm.value for arm in plan.arm_order],
            "status": "ACTIVE",
            "running_arm": None,
            "running_grader": None,
        },
    )
    saved = CampaignArmArtifact(
        receipt=ArmExecutionReceipt(
            arm=first_arm,
            manifest_identity=first_manifest.identity,
            status="PASS",
            model_called=True,
            total_model_tokens=1,
            requests=1,
        ),
        patch_sha256=sha256_bytes(b"saved-patch"),
        patch_bytes=1,
        evidence_sha256=sha256_bytes(b"saved-evidence"),
    )
    _atomic_write_json(attempt_dir / f"arm-{first_arm.value}.json", saved.to_dict())

    progress = runner.run(paid_authorized=True, max_new_pairs=1)

    assert progress.completed_pairs == 1
    assert executor.calls == [(entry.pair_id, plan.arm_order[1])]
    assert {arm for pair, arm in grader.calls if pair == entry.pair_id} == {
        ExperimentArm.STOCK,
        ExperimentArm.ADCP,
    }


def test_resume_running_arm_without_artifact_excludes_accounting_unknown(tmp_path: Path, monkeypatch) -> None:
    runner, schedule, executor, grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)
    runner._initialize_or_validate_campaign()

    entry = schedule.entries[0]
    plan = runner.plan_factory(entry)
    running_arm = plan.arm_order[0]
    attempt_dir = runner.pairs_root / entry.pair_id / "attempt-0000"
    attempt_dir.mkdir(parents=True)
    _atomic_write_json(
        attempt_dir / "attempt.json",
        {
            "schema_version": 1,
            "pair_id": entry.pair_id,
            "task_id": entry.task_id,
            "repeat_index": entry.repeat_index,
            "seed": entry.seed,
            "attempt_index": 0,
            "pair_identity": str(plan.pair_identity),
            "execution_order": [arm.value for arm in plan.arm_order],
            "status": "RUNNING_ARM",
            "running_arm": running_arm.value,
            "running_grader": None,
        },
    )

    with pytest.raises(CampaignRecoveryRequired, match="accounting may be unknown"):
        runner.run(paid_authorized=True, max_new_pairs=1)

    assert executor.calls == []
    assert grader.calls == []
    ledger = json.loads(runner.ledger_path.read_text(encoding="utf-8"))
    assert len(ledger["attempts"]) == 1
    attempt = ledger["attempts"][0]
    assert attempt["exclusion_reason"] == ExclusionReason.EXPERIMENT_ACCOUNTING_UNKNOWN.value
    assert attempt["stock_resolved"] is None
    assert attempt["adcp_resolved"] is None

    progress = runner.run(paid_authorized=True, max_new_pairs=1)
    assert progress.completed_pairs == 1
    assert progress.excluded_attempts == 1
    assert len(executor.calls) == 2


def test_pre_dispatch_failure_records_exclusion_without_counting_pair(tmp_path: Path, monkeypatch) -> None:
    executor = PreDispatchOnceExecutor()
    runner, _schedule, _executor, grader = _campaign(tmp_path, executor=executor)
    _skip_git_identity(monkeypatch)

    with pytest.raises(CampaignRecoveryRequired, match="excluded before dispatch"):
        runner.run(paid_authorized=True, max_new_pairs=1)

    progress = runner.progress()
    assert progress.completed_pairs == 0
    assert progress.excluded_attempts == 1
    assert grader.calls == []


def test_campaign_workspace_identity_drift_is_refused_before_executor(tmp_path: Path, monkeypatch) -> None:
    runner, _schedule, executor, grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)
    runner._initialize_or_validate_campaign()
    state = json.loads(runner.campaign_path.read_text(encoding="utf-8"))
    state["schedule_identity"] = "sha256:" + "f" * 64
    _atomic_write_json(runner.campaign_path, state)

    with pytest.raises(Phase3DCampaignError, match="different immutable experiment"):
        runner.run(paid_authorized=True, max_new_pairs=1)

    assert executor.calls == []
    assert grader.calls == []


def test_durable_ledger_is_directly_compatible_with_existing_outcome_blind_auditor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner, _schedule, _executor, _grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)
    progress = runner.run(paid_authorized=True, max_new_pairs=1)
    assert progress.completed_pairs == 1

    completed = subprocess.run(
        [
            sys.executable,
            "tools/phase3d_analyze_paired_results.py",
            str(runner.ledger_path),
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["completed_pairs"] == 1
    assert payload["expected_pairs"] == 370
    assert payload["treatment_effect_exposed"] is False
    assert payload["p_value_exposed"] is False
    assert payload["winner_exposed"] is False


def test_public_progress_contains_no_per_arm_outcomes_or_winner(tmp_path: Path, monkeypatch) -> None:
    runner, _schedule, _executor, _grader = _campaign(tmp_path)
    _skip_git_identity(monkeypatch)
    progress = runner.run(paid_authorized=True, max_new_pairs=1).to_public_dict()

    text = json.dumps(progress, sort_keys=True)
    assert "stock_resolved" not in text
    assert "adcp_resolved" not in text
    assert "paired_effect" not in text
    assert progress["winner_exposed"] is False
