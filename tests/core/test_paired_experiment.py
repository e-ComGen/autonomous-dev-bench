from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from benchmark_core.experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ModelManifest,
    TaskManifest,
)
from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_experiment import (
    ArmExecutionReceipt,
    DryRunModelCallForbidden,
    ExperimentArm,
    PairFairnessError,
    PaidAdmissionSnapshot,
    PaidExperimentBlocked,
    PairedExperimentController,
    PairedExperimentPlan,
    require_causal_pair,
)


ROOT = Path(__file__).resolve().parents[2]
SHA = "sha256:" + "a" * 64
TASK_COMMIT = "1" * 40
STOCK_COMMIT = "a66e4702047846cdaa10c66c9d3df3951f5ea70d"
ADCP_COMMIT = "285702063815280398b95ba8696566259c8b5b34"
ADMISSION_SOURCES = (
    "PHASE3D_EXPERIMENT_PLAN.json",
    "migration/swebench_v5_verified_parity.json",
    "HARBOR.lock.json",
    "DEEPSEEK_HARNESS.lock.json",
    "ADCP.lock.json",
    "DEEPSEEK_V4_ESTIMATOR.lock.json",
)


def _plan(*, seed: int = 17) -> PairedExperimentPlan:
    """Generic plan used only by controller/fairness dry-run tests."""
    return PairedExperimentPlan(
        pair_id="phase3d-verified-pair-0",
        task=TaskManifest(
            dataset="swebench_verified",
            dataset_version="v5",
            task_id="psf__requests-1142",
            task_repo_commit=TASK_COMMIT,
            environment_image_digest=SHA,
            evaluator_version="5.0.2",
        ),
        stock_agent=AgentManifest(
            implementation="stock_deepseek_harness",
            commit=STOCK_COMMIT,
            configuration={"profile": "sdk"},
        ),
        adcp_agent=AgentManifest(
            implementation="adcp_zone_development",
            commit=ADCP_COMMIT,
            configuration={"runtime": "assured_runtime"},
        ),
        model=ModelManifest(
            identifier="deepseek-v4-flash",
            provider_route="deepseek-official",
            decoding={"temperature": 0},
        ),
        budget=BudgetManifest(
            input_token_cap=100000,
            output_token_cap=50000,
            total_model_token_cap=120000,
            max_requests=64,
            wall_time_seconds=3600,
            patch_byte_cap=1000000,
        ),
        execution=ExecutionManifest(
            engine="harbor",
            engine_version="0.22.0",
            provider="docker",
            network_policy="task_policy",
            resource_policy={"cpu": 8, "memory_mb": 16384},
        ),
        repeat_index=0,
        seed=seed,
    )


def _copy_admission_sources(tmp_path: Path) -> None:
    for relative in ADMISSION_SOURCES:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_locks(tmp_path: Path, *, ready: bool) -> None:
    """Create a repository-shaped admission fixture from accepted real locks."""
    _copy_admission_sources(tmp_path)

    estimator_path = tmp_path / "DEEPSEEK_V4_ESTIMATOR.lock.json"
    estimator = json.loads(estimator_path.read_text(encoding="utf-8"))
    estimator["live_provider_prompt_usage_parity"] = ready
    estimator["paid_ready"] = ready
    estimator["production_blocker"] = None if ready else "LIVE_PROVIDER_PROMPT_USAGE_PARITY_NOT_RUN"
    _write_json(estimator_path, estimator)

    adcp_path = tmp_path / "ADCP.lock.json"
    adcp = json.loads(adcp_path.read_text(encoding="utf-8"))
    adcp["private_pinned_runtime_qualification_status"] = "PASS" if ready else "NOT_RUN"
    adcp["paid_ready"] = ready
    adcp["production_blocker"] = None if ready else "PINNED_PRIVATE_ADCP_RUNTIME_NOT_QUALIFIED"
    _write_json(adcp_path, adcp)

    if ready:
        plan_path = tmp_path / "PHASE3D_EXPERIMENT_PLAN.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
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
        _write_json(plan_path, plan)


def _ready_plan(admission: PaidAdmissionSnapshot, *, task_id: str = "psf__requests-1142", repeat_index: int = 0) -> PairedExperimentPlan:
    design = admission.experiment_design
    assert design.design_paid_ready
    assert design.input_token_cap_per_arm is not None
    assert design.output_token_cap_per_arm is not None
    assert design.total_model_token_cap_per_arm is not None
    assert design.max_requests_per_arm is not None
    assert design.wall_time_seconds_per_arm is not None
    assert design.patch_byte_cap_per_arm is not None

    return PairedExperimentPlan(
        pair_id=design.expected_pair_id(task_id, repeat_index),
        task=TaskManifest(
            dataset="verified",
            dataset_version=design.official_swebench_version,
            task_id=task_id,
            task_repo_commit=design.task_repo_commit,
            environment_image_digest=SHA,
            evaluator_version=design.official_swebench_version,
        ),
        stock_agent=AgentManifest(
            implementation="stock_deepseek_harness",
            commit=design.stock_commit,
            configuration={"profile": "sdk"},
        ),
        adcp_agent=AgentManifest(
            implementation="adcp_zone_development",
            commit=design.adcp_commit,
            configuration={"runtime": "assured_runtime"},
        ),
        model=ModelManifest(
            identifier=design.model,
            provider_route=design.provider,
            decoding={"temperature": 0},
        ),
        budget=BudgetManifest(
            input_token_cap=design.input_token_cap_per_arm,
            output_token_cap=design.output_token_cap_per_arm,
            total_model_token_cap=design.total_model_token_cap_per_arm,
            max_requests=design.max_requests_per_arm,
            wall_time_seconds=design.wall_time_seconds_per_arm,
            patch_byte_cap=design.patch_byte_cap_per_arm,
        ),
        execution=ExecutionManifest(
            engine="harbor",
            engine_version=design.harbor_version,
            provider=design.environment_provider,
            network_policy="task_policy",
            resource_policy={"fixture": "same-both-arms"},
        ),
        repeat_index=repeat_index,
        seed=design.expected_seed(task_id, repeat_index),
        order_algorithm=design.pair_order_algorithm,
    )


class RecordingExecutor:
    def __init__(self, *, model_called: bool = False, wrong_identity: bool = False) -> None:
        self.model_called = model_called
        self.wrong_identity = wrong_identity
        self.calls: list[ExperimentArm] = []

    def execute(self, manifest, arm):
        self.calls.append(arm)
        identity = manifest.identity
        if self.wrong_identity:
            identity = Sha256Digest("sha256:" + "b" * 64)
        return ArmExecutionReceipt(
            arm=arm,
            manifest_identity=identity,
            status="PASS",
            model_called=self.model_called,
            total_model_tokens=1 if self.model_called else 0,
            requests=1 if self.model_called else 0,
        )


def test_pair_materializes_two_atomic_manifests_with_identical_causal_controls() -> None:
    plan = _plan()
    manifests = plan.manifests()
    stock = manifests[ExperimentArm.STOCK]
    adcp = manifests[ExperimentArm.ADCP]

    assert stock.task == adcp.task
    assert stock.model == adcp.model
    assert stock.budget == adcp.budget
    assert stock.execution == adcp.execution
    assert stock.trial == adcp.trial
    assert stock.agent != adcp.agent
    assert stock.experiment_id.endswith("-stock")
    assert adcp.experiment_id.endswith("-adcp")


def test_arm_order_is_deterministic_and_contains_each_arm_once() -> None:
    plan = _plan(seed=991)
    assert plan.arm_order == _plan(seed=991).arm_order
    assert set(plan.arm_order) == {ExperimentArm.STOCK, ExperimentArm.ADCP}
    assert len(plan.arm_order) == 2


def test_fairness_rejects_budget_drift_between_atomic_arms() -> None:
    plan = _plan()
    manifests = plan.manifests()
    stock = manifests[ExperimentArm.STOCK]
    adcp = replace(
        manifests[ExperimentArm.ADCP],
        budget=BudgetManifest(1, 1, 2, 1, 1, 1),
    )

    with pytest.raises(PairFairnessError, match="budget"):
        require_causal_pair(stock, adcp)


def test_repository_admission_snapshot_fails_closed_until_all_paid_gates_pass(tmp_path: Path) -> None:
    _write_locks(tmp_path, ready=False)
    admission = PaidAdmissionSnapshot.from_repository(tmp_path)

    assert admission.experiment_design.design_paid_ready is True
    assert not admission.paid_ready
    assert admission.blockers == (
        "DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS",
        "DEEPSEEK_ESTIMATOR_NOT_PAID_READY",
        "ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS",
        "ADCP_NOT_PAID_READY",
    )
    with pytest.raises(PaidExperimentBlocked):
        admission.require_paid_ready(_plan())


def test_repository_admission_snapshot_binds_design_and_accepts_complete_evidence(tmp_path: Path) -> None:
    _write_locks(tmp_path, ready=True)
    admission = PaidAdmissionSnapshot.from_repository(tmp_path)
    plan = _ready_plan(admission)

    assert admission.paid_ready
    assert admission.blockers == ()
    assert admission.experiment_design.design_paid_ready
    assert str(admission.experiment_design.plan_digest).startswith("sha256:")
    assert str(admission.estimator_lock_digest).startswith("sha256:")
    admission.require_paid_ready(plan)


def test_ready_admission_rejects_runtime_pair_budget_or_seed_drift(tmp_path: Path) -> None:
    _write_locks(tmp_path, ready=True)
    admission = PaidAdmissionSnapshot.from_repository(tmp_path)
    plan = _ready_plan(admission)

    with pytest.raises(PaidExperimentBlocked, match="seed"):
        admission.require_paid_ready(replace(plan, seed=plan.seed + 1))

    bad_budget = BudgetManifest(
        input_token_cap=plan.budget.input_token_cap,
        output_token_cap=plan.budget.output_token_cap,
        total_model_token_cap=plan.budget.total_model_token_cap - 1,
        max_requests=plan.budget.max_requests,
        wall_time_seconds=plan.budget.wall_time_seconds,
        patch_byte_cap=plan.budget.patch_byte_cap,
    )
    with pytest.raises(PaidExperimentBlocked, match="budget"):
        admission.require_paid_ready(replace(plan, budget=bad_budget))


def test_paid_controller_checks_admission_before_invoking_any_executor(tmp_path: Path) -> None:
    _write_locks(tmp_path, ready=False)
    admission = PaidAdmissionSnapshot.from_repository(tmp_path)
    stock = RecordingExecutor(model_called=True)
    adcp = RecordingExecutor(model_called=True)

    with pytest.raises(PaidExperimentBlocked):
        PairedExperimentController().run(
            _plan(),
            {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp},
            paid=True,
            admission=admission,
        )

    assert stock.calls == []
    assert adcp.calls == []


def test_dry_run_executes_both_arms_in_precommitted_order_without_model_calls() -> None:
    plan = _plan(seed=1234)
    stock = RecordingExecutor()
    adcp = RecordingExecutor()

    receipt = PairedExperimentController().run(
        plan,
        {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp},
        paid=False,
    )

    observed = tuple(item.arm for item in receipt.arm_receipts)
    assert receipt.execution_order == plan.arm_order
    assert observed == plan.arm_order
    assert receipt.pair_identity == plan.pair_identity
    assert receipt.paid is False
    assert receipt.admission_identity is None


def test_dry_run_rejects_any_model_call() -> None:
    plan = _plan()
    stock = RecordingExecutor(model_called=True)
    adcp = RecordingExecutor()

    with pytest.raises(DryRunModelCallForbidden):
        PairedExperimentController().run(
            plan,
            {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp},
            paid=False,
        )


def test_executor_receipt_must_bind_exact_planned_manifest() -> None:
    plan = _plan()
    stock = RecordingExecutor(wrong_identity=True)
    adcp = RecordingExecutor()

    with pytest.raises(PairFairnessError, match="manifest identity"):
        PairedExperimentController().run(
            plan,
            {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp},
            paid=False,
        )


def test_paid_run_with_complete_admission_records_admission_identity(tmp_path: Path) -> None:
    _write_locks(tmp_path, ready=True)
    admission = PaidAdmissionSnapshot.from_repository(tmp_path)
    plan = _ready_plan(admission, repeat_index=1)
    stock = RecordingExecutor(model_called=True)
    adcp = RecordingExecutor(model_called=True)

    receipt = PairedExperimentController().run(
        plan,
        {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp},
        paid=True,
        admission=admission,
    )

    assert receipt.paid is True
    assert receipt.admission_identity == admission.content_digest
    assert tuple(item.arm for item in receipt.arm_receipts) == plan.arm_order
