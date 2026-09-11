"""Zero-paid coverage of the two Phase 3D arm executors and the official grader.

Only the Harbor launcher and the official evaluator are replaced; the durable
campaign, the artifact contract, the accounting rules and the grading seam are
the production code path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_analysis import PairedExperimentSchedule
from benchmark_core.paired_experiment import ExperimentArm, PaidAdmissionSnapshot
from benchmark_core.phase3d_campaign import (
    CampaignArmArtifact,
    DurablePhase3DCampaign,
    ExperimentAccountingUnknownFailure,
    OfficialGradeArtifact,
    PreDispatchInfrastructureFailure,
    materialize_pair_plan,
    sha256_bytes,
)
from benchmark_core.swebench_v5 import OUTCOME_RESOLVED, OfficialResolution
from suites.coding.phase3d_execution import (
    ADCP_FAKE_ENV,
    ADCP_AGENT,
    STOCK_FAKE_ENV,
    STOCK_AGENT,
    ADCPSemanticsV2ArmExecutor,
    BothArmsCampaignExecutor,
    CampaignArmGrader,
    HarborTrialRequest,
    HarborTrialResult,
    StockDeepSeekArmExecutor,
)


ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "astropy__astropy-12907"
IMAGE_DIGEST = "sha256:" + "a" * 64
REPORT_DIGEST = Sha256Digest("sha256:" + "b" * 64)


class _Launcher:
    """Answers each trial with scripted agent metadata; records every request."""

    def __init__(
        self,
        *,
        patch: str = "diff --git a/a b/a\n",
        fake_model: bool = True,
        accounting: dict[str, object] | None = None,
    ) -> None:
        self.patch = patch
        self.fake_model = fake_model
        self.accounting = accounting
        self.requests: list[HarborTrialRequest] = []

    def launch(self, request: HarborTrialRequest) -> HarborTrialResult:
        self.requests.append(request)
        if request.agent_import_path == STOCK_AGENT:
            metadata: dict[str, object] = {
                "agent": "stock_deepseek_harness",
                "task_level_failure": not self.patch.strip(),
                "fake_model": self.fake_model,
            }
        else:
            metadata = {
                "agent": "adcp",
                "outcome_status": "CANDIDATE_READY" if self.patch.strip() else "FAILED_BOUNDED",
                "model_called": not self.fake_model,
                "task_level_failure": not self.patch.strip(),
            }
        accounting = self.accounting if self.accounting is not None else {"total_model_tokens": 0, "requests": 0}
        if self.accounting is not None or not self.fake_model:
            metadata["budget_proxy"] = accounting
        return HarborTrialResult(
            trial_dir=request.trials_dir / request.trial_name,
            agent_metadata=metadata,
            patch=self.patch,
        )


class _Evaluator:
    """Stands in for the pinned official CLI; reports what it was asked to score."""

    def __init__(self, *, resolved: bool = True, verdict: bool | None = True) -> None:
        self.resolved = resolved
        self.verdict = verdict
        self.graded: list[tuple[str, str]] = []

    def evaluate(self, *, instance_id: str, patch: str, run_id: str):
        self.graded.append((instance_id, patch))
        if self.verdict is None:
            resolution = OfficialResolution(instance_id=instance_id, outcome="INFRA_FAILURE", resolved=None)
        else:
            resolution = OfficialResolution(instance_id=instance_id, outcome=OUTCOME_RESOLVED, resolved=self.resolved)
        return resolution, REPORT_DIGEST


def _executors(tmp_path: Path, launcher: _Launcher, *, task_dirs: dict[str, Path] | None = None, adcp_env=None):
    task_dirs = task_dirs if task_dirs is not None else {TASK_ID: tmp_path / "task"}
    stock = StockDeepSeekArmExecutor(
        task_dirs=task_dirs, launcher=launcher, controller_env={STOCK_FAKE_ENV: "1"}
    )
    adcp = ADCPSemanticsV2ArmExecutor(
        task_dirs=task_dirs,
        launcher=launcher,
        controller_env={ADCP_FAKE_ENV: "1", **(adcp_env or {})},
    )
    return stock, adcp, BothArmsCampaignExecutor(stock, adcp)


def _plan():
    admission = PaidAdmissionSnapshot.from_repository(ROOT)
    schedule = PairedExperimentSchedule.from_design(admission.experiment_design)
    first = schedule.entries[0]
    return (
        admission,
        schedule,
        first,
        materialize_pair_plan(admission, first, environment_image_digest=IMAGE_DIGEST),
    )


def test_executor_returns_a_durable_arm_artifact_bound_to_its_manifest(tmp_path):
    admission, _schedule, _entry, plan = _plan()
    launcher = _Launcher()
    stock, adcp, _both = _executors(tmp_path, launcher)
    attempt = tmp_path / "attempt-0000"

    stock_artifact = stock.execute_arm(plan, ExperimentArm.STOCK, attempt)
    adcp_artifact = adcp.execute_arm(plan, ExperimentArm.ADCP, attempt)

    stock_manifest = plan.manifest_for(ExperimentArm.STOCK)
    adcp_manifest = plan.manifest_for(ExperimentArm.ADCP)
    assert stock_artifact.receipt.arm is ExperimentArm.STOCK
    assert stock_artifact.receipt.manifest_identity == stock_manifest.identity
    assert adcp_artifact.receipt.manifest_identity == adcp_manifest.identity
    assert stock_artifact.receipt.manifest_identity != adcp_artifact.receipt.manifest_identity

    patch = (attempt / "patch-stock.diff").read_text(encoding="utf-8")
    assert str(stock_artifact.patch_sha256) == "sha256:" + hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert stock_artifact.patch_bytes == len(patch.encode("utf-8"))
    evidence = (attempt / "evidence-stock.json").read_bytes()
    assert str(stock_artifact.evidence_sha256) == "sha256:" + hashlib.sha256(evidence).hexdigest()
    assert adcp_artifact.receipt.status == "CANDIDATE_READY"


def test_fake_model_arm_reports_no_model_call_and_zero_usage(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    stock, adcp, _both = _executors(tmp_path, _Launcher())

    for executor, arm in ((stock, ExperimentArm.STOCK), (adcp, ExperimentArm.ADCP)):
        artifact = executor.execute_arm(plan, arm, tmp_path / f"attempt-{arm.value}")
        assert artifact.receipt.model_called is False
        assert (artifact.receipt.total_model_tokens, artifact.receipt.requests) == (0, 0)


def test_model_calling_arm_without_exact_proxy_accounting_is_an_accounting_exclusion(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    launcher = _Launcher(fake_model=False, accounting={"total_model_tokens": 10})
    stock = StockDeepSeekArmExecutor(
        task_dirs={TASK_ID: tmp_path / "task"}, launcher=launcher, controller_env={}
    )

    with pytest.raises(ExperimentAccountingUnknownFailure):
        stock.execute_arm(plan, ExperimentArm.STOCK, tmp_path / "attempt-0000")


def test_missing_task_directory_is_a_pre_dispatch_failure(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    stock, _adcp, _both = _executors(tmp_path, _Launcher(), task_dirs={})

    with pytest.raises(PreDispatchInfrastructureFailure, match=TASK_ID):
        stock.execute_arm(plan, ExperimentArm.STOCK, tmp_path / "attempt-0000")


def test_grader_scores_the_recorded_patch_and_binds_the_official_report(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    launcher = _Launcher()
    stock, _adcp, _both = _executors(tmp_path, launcher)
    attempt = tmp_path / "attempt-0000"
    artifact = stock.execute_arm(plan, ExperimentArm.STOCK, attempt)
    evaluator = _Evaluator(resolved=True)

    grade = CampaignArmGrader(evaluator).grade_arm(plan, ExperimentArm.STOCK, artifact, attempt)

    assert grade == OfficialGradeArtifact(resolved=True, evidence_sha256=REPORT_DIGEST)
    assert evaluator.graded == [(TASK_ID, launcher.patch)]


def test_grader_refuses_a_patch_that_no_longer_matches_the_recorded_digest(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    stock, _adcp, _both = _executors(tmp_path, _Launcher())
    attempt = tmp_path / "attempt-0000"
    artifact = stock.execute_arm(plan, ExperimentArm.STOCK, attempt)
    (attempt / "patch-stock.diff").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(Exception, match="patch digest"):
        CampaignArmGrader(_Evaluator()).grade_arm(plan, ExperimentArm.STOCK, artifact, attempt)


def test_grader_refuses_an_official_report_without_a_task_verdict(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    stock, _adcp, _both = _executors(tmp_path, _Launcher())
    attempt = tmp_path / "attempt-0000"
    artifact = stock.execute_arm(plan, ExperimentArm.STOCK, attempt)

    with pytest.raises(Exception, match="no task verdict"):
        CampaignArmGrader(_Evaluator(verdict=None)).grade_arm(plan, ExperimentArm.STOCK, artifact, attempt)


def test_real_executors_drive_the_durable_campaign_over_a_fake_model(tmp_path, monkeypatch):
    admission, schedule, entry, _plan_for_first = _plan()
    assert admission.paid_ready, "this end-to-end test requires the locked paid-ready admission"
    launcher = _Launcher()
    _stock, _adcp, both = _executors(tmp_path, launcher)
    grader = CampaignArmGrader(_Evaluator(resolved=True))
    campaign = DurablePhase3DCampaign(
        repository_root=ROOT,
        workspace=tmp_path / "campaign",
        expected_benchmark_commit="fixture-commit-check-is-monkeypatched",
        admission=admission,
        schedule=schedule,
        plan_factory=lambda item: materialize_pair_plan(
            admission, item, environment_image_digest=IMAGE_DIGEST
        ),
        executor=both,
        grader=grader,
    )
    monkeypatch.setattr(DurablePhase3DCampaign, "_require_exact_repository_commit", lambda self: None)

    progress = campaign.run(paid_authorized=True, max_new_pairs=1)

    assert (progress.completed_pairs, progress.excluded_attempts) == (1, 0)
    assert sorted(request.agent_import_path for request in launcher.requests) == [ADCP_AGENT, STOCK_AGENT]
    ledger = json.loads(campaign.ledger_path.read_text(encoding="utf-8"))
    attempt = ledger["attempts"][0]
    assert attempt["pair_id"] == entry.pair_id
    assert attempt["stock_resolved"] is True and attempt["adcp_resolved"] is True
    assert attempt["stock_grader_evidence"] == str(REPORT_DIGEST)


def test_adcp_arm_never_receives_the_upstream_provider_credential(tmp_path):
    _admission, _schedule, _entry, plan = _plan()
    launcher = _Launcher()
    _stock, _adcp, _both = _executors(
        tmp_path,
        launcher,
        adcp_env={
            "AUTOBENCH_MODEL_PROXY_BASE_URL": "http://127.0.0.1:8791/v1",
            "AUTOBENCH_MODEL_PROXY_TOKEN": "proxy-token",
        },
    )
    _adcp.execute_arm(plan, ExperimentArm.ADCP, tmp_path / "attempt-0000")

    adcp_request = next(r for r in launcher.requests if r.agent_import_path == ADCP_AGENT)
    assert adcp_request.controller_env["AUTOBENCH_MODEL_PROXY_TOKEN"] == "proxy-token"
    assert not any("UPSTREAM_API_KEY" in name for name in adcp_request.controller_env)
