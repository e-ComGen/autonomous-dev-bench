"""Paired causal-experiment controller for Stock vs ADCP coding trials.

The pair owns the scientific invariants shared by both arms. Atomic
``ExperimentManifest`` objects remain the identity of one arm; this module owns
the relationship between two such manifests and the fail-closed admission gate
for paid execution.

Dry runs are allowed while production qualification is incomplete, but a dry
run is forbidden from making a model call. Paid execution is impossible until
both the preregistered experiment design and all external qualification locks
are explicitly ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from .experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ExperimentManifest,
    ModelManifest,
    TaskManifest,
    TrialManifest,
)
from .experiment_preregistration import ExperimentDesignSnapshot, ExperimentPlanInvalid
from .identity import CanonicalModel, Sha256Digest, require_identifier


EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_PROVIDER = "deepseek-official"


class ExperimentArm(str, Enum):
    STOCK = "stock"
    ADCP = "adcp"


class PairFairnessError(ValueError):
    """The two arms do not differ only at the intended agent boundary."""


class PaidExperimentBlocked(RuntimeError):
    """Paid execution was requested before all qualification gates passed."""


class DryRunModelCallForbidden(RuntimeError):
    """A dry-run executor attempted to use a model."""


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PaidExperimentBlocked(f"cannot read admission lock: {path.name}") from error
    if not isinstance(value, dict):
        raise PaidExperimentBlocked(f"admission lock is not an object: {path.name}")
    return value


@dataclass(frozen=True, slots=True)
class PaidAdmissionSnapshot(CanonicalModel):
    """Immutable evidence + preregistration snapshot consulted before paid execution."""

    expected_model: str
    expected_provider: str
    experiment_design: ExperimentDesignSnapshot
    estimator_live_prompt_parity: bool
    estimator_paid_ready: bool
    adcp_fake_process_boundary_pass: bool
    adcp_private_runtime_status: str
    adcp_paid_ready: bool
    stock_model_matches: bool
    adcp_model_matches: bool
    estimator_model_matches: bool
    provider_routes_match: bool
    estimator_lock_digest: Sha256Digest
    adcp_lock_digest: Sha256Digest
    stock_harness_lock_digest: Sha256Digest

    def __post_init__(self) -> None:
        require_identifier(self.expected_model, "expected_model")
        require_identifier(self.expected_provider, "expected_provider")
        require_identifier(self.adcp_private_runtime_status, "adcp_private_runtime_status")
        if not isinstance(self.experiment_design, ExperimentDesignSnapshot):
            raise ValueError("experiment_design must be an ExperimentDesignSnapshot")
        for name in (
            "estimator_live_prompt_parity",
            "estimator_paid_ready",
            "adcp_fake_process_boundary_pass",
            "adcp_paid_ready",
            "stock_model_matches",
            "adcp_model_matches",
            "estimator_model_matches",
            "provider_routes_match",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        for name in ("estimator_lock_digest", "adcp_lock_digest", "stock_harness_lock_digest"):
            value = getattr(self, name)
            if not isinstance(value, Sha256Digest):
                object.__setattr__(self, name, Sha256Digest(str(value)))

    @classmethod
    def from_repository(cls, root: str | Path) -> "PaidAdmissionSnapshot":
        root_path = Path(root)
        design = ExperimentDesignSnapshot.from_repository(root_path)
        estimator = _load_object(root_path / "DEEPSEEK_V4_ESTIMATOR.lock.json")
        adcp = _load_object(root_path / "ADCP.lock.json")
        stock = _load_object(root_path / "DEEPSEEK_HARNESS.lock.json")

        stock_provider = stock.get("provider")
        adcp_provider = adcp.get("provider_route")
        estimator_model = estimator.get("model_route")
        stock_model = stock.get("model")
        adcp_model = adcp.get("model_route")

        return cls(
            expected_model=EXPECTED_MODEL,
            expected_provider=EXPECTED_PROVIDER,
            experiment_design=design,
            estimator_live_prompt_parity=estimator.get("live_provider_prompt_usage_parity") is True,
            estimator_paid_ready=estimator.get("paid_ready") is True,
            adcp_fake_process_boundary_pass=adcp.get("fake_process_boundary_status") == "PASS",
            adcp_private_runtime_status=str(adcp.get("private_pinned_runtime_qualification_status", "MISSING")),
            adcp_paid_ready=adcp.get("paid_ready") is True,
            stock_model_matches=stock_model == EXPECTED_MODEL,
            adcp_model_matches=adcp_model == EXPECTED_MODEL,
            estimator_model_matches=estimator_model == EXPECTED_MODEL,
            provider_routes_match=(stock_provider == EXPECTED_PROVIDER and adcp_provider == EXPECTED_PROVIDER),
            estimator_lock_digest=Sha256Digest.of(estimator),
            adcp_lock_digest=Sha256Digest.of(adcp),
            stock_harness_lock_digest=Sha256Digest.of(stock),
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = list(self.experiment_design.design_blockers)
        if not self.estimator_live_prompt_parity:
            blockers.append("DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS")
        if not self.estimator_paid_ready:
            blockers.append("DEEPSEEK_ESTIMATOR_NOT_PAID_READY")
        if not self.adcp_fake_process_boundary_pass:
            blockers.append("ADCP_PUBLIC_PROCESS_BOUNDARY_NOT_PASS")
        if self.adcp_private_runtime_status != "PASS":
            blockers.append("ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS")
        if not self.adcp_paid_ready:
            blockers.append("ADCP_NOT_PAID_READY")
        if not self.stock_model_matches:
            blockers.append("STOCK_MODEL_IDENTITY_MISMATCH")
        if not self.adcp_model_matches:
            blockers.append("ADCP_MODEL_IDENTITY_MISMATCH")
        if not self.estimator_model_matches:
            blockers.append("ESTIMATOR_MODEL_IDENTITY_MISMATCH")
        if not self.provider_routes_match:
            blockers.append("PROVIDER_ROUTE_MISMATCH")
        return tuple(blockers)

    @property
    def paid_ready(self) -> bool:
        return not self.blockers

    def require_paid_ready(self, plan: "PairedExperimentPlan") -> None:
        if self.blockers:
            raise PaidExperimentBlocked("paid experiment blocked: " + ",".join(self.blockers))
        _require_runtime_pair_matches_design(plan, self.experiment_design)


def _require_runtime_pair_matches_design(plan: "PairedExperimentPlan", design: ExperimentDesignSnapshot) -> None:
    """Bind one concrete runtime pair to the already-locked outcome-blind design."""
    if not design.design_paid_ready:
        raise PaidExperimentBlocked("experiment design is not paid-ready")
    task_id = plan.task.task_id
    try:
        expected_pair_id = design.expected_pair_id(task_id, plan.repeat_index)
        expected_seed = design.expected_seed(task_id, plan.repeat_index)
    except ExperimentPlanInvalid as error:
        raise PaidExperimentBlocked(str(error)) from error

    mismatches: list[str] = []
    if plan.pair_id != expected_pair_id:
        mismatches.append("pair_id")
    if plan.seed != expected_seed:
        mismatches.append("seed")
    if plan.order_algorithm != design.pair_order_algorithm:
        mismatches.append("pair_order_algorithm")
    if str(plan.task.task_repo_commit) != design.task_repo_commit:
        mismatches.append("task_repo_commit")
    if plan.task.evaluator_version != design.official_swebench_version:
        mismatches.append("official_swebench_version")
    if plan.stock_agent.implementation != "stock_deepseek_harness" or str(plan.stock_agent.commit) != design.stock_commit:
        mismatches.append("stock_agent")
    if plan.adcp_agent.implementation != "adcp_zone_development" or str(plan.adcp_agent.commit) != design.adcp_commit:
        mismatches.append("adcp_agent")
    if plan.model.identifier != design.model or plan.model.provider_route != design.provider:
        mismatches.append("model")

    expected_budget = (
        design.input_token_cap_per_arm,
        design.output_token_cap_per_arm,
        design.total_model_token_cap_per_arm,
        design.max_requests_per_arm,
        design.wall_time_seconds_per_arm,
        design.patch_byte_cap_per_arm,
    )
    observed_budget = (
        plan.budget.input_token_cap,
        plan.budget.output_token_cap,
        plan.budget.total_model_token_cap,
        plan.budget.max_requests,
        plan.budget.wall_time_seconds,
        plan.budget.patch_byte_cap,
    )
    if observed_budget != expected_budget:
        mismatches.append("budget")
    if plan.execution.engine != "harbor" or plan.execution.engine_version != design.harbor_version:
        mismatches.append("harbor")
    if plan.execution.provider != design.environment_provider:
        mismatches.append("environment_provider")

    if mismatches:
        raise PaidExperimentBlocked("runtime pair differs from preregistered design: " + ",".join(mismatches))


@dataclass(frozen=True, slots=True)
class PairedExperimentPlan(CanonicalModel):
    """Immutable shared identity for one Stock-vs-ADCP paired repeat."""

    pair_id: str
    task: TaskManifest
    stock_agent: AgentManifest
    adcp_agent: AgentManifest
    model: ModelManifest
    budget: BudgetManifest
    execution: ExecutionManifest
    repeat_index: int
    seed: int
    order_algorithm: str = "sha256-parity-v1"
    schema_version: str = "1"

    def __post_init__(self) -> None:
        require_identifier(self.pair_id, "pair_id")
        require_identifier(self.order_algorithm, "order_algorithm")
        require_identifier(self.schema_version, "schema_version")
        _non_negative_int(self.repeat_index, "repeat_index")
        _non_negative_int(self.seed, "seed")
        if self.stock_agent == self.adcp_agent:
            raise PairFairnessError("paired arms require distinct agent manifests")
        if self.stock_agent.implementation == self.adcp_agent.implementation:
            raise PairFairnessError("paired arms require distinct agent implementations")

    @property
    def pair_identity(self) -> Sha256Digest:
        return self.content_digest

    @property
    def arm_order(self) -> tuple[ExperimentArm, ExperimentArm]:
        if self.order_algorithm != "sha256-parity-v1":
            raise PairFairnessError("unsupported arm ordering algorithm")
        payload = f"{self.pair_id}\0{self.task.task_id}\0{self.repeat_index}\0{self.seed}".encode("utf-8")
        first_stock = (hashlib.sha256(payload).digest()[0] & 1) == 0
        return (ExperimentArm.STOCK, ExperimentArm.ADCP) if first_stock else (ExperimentArm.ADCP, ExperimentArm.STOCK)

    def manifest_for(self, arm: ExperimentArm) -> ExperimentManifest:
        if not isinstance(arm, ExperimentArm):
            arm = ExperimentArm(arm)
        agent = self.stock_agent if arm is ExperimentArm.STOCK else self.adcp_agent
        return ExperimentManifest(
            experiment_id=f"{self.pair_id}-{arm.value}",
            task=self.task,
            agent=agent,
            model=self.model,
            budget=self.budget,
            execution=self.execution,
            trial=TrialManifest(repeat_index=self.repeat_index, seed=self.seed),
        )

    def manifests(self) -> Mapping[ExperimentArm, ExperimentManifest]:
        stock = self.manifest_for(ExperimentArm.STOCK)
        adcp = self.manifest_for(ExperimentArm.ADCP)
        require_causal_pair(stock, adcp)
        return {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp}


def require_causal_pair(stock: ExperimentManifest, adcp: ExperimentManifest) -> None:
    """Require equality of every causal control except agent implementation."""
    mismatches: list[str] = []
    for name in ("task", "model", "budget", "execution"):
        if getattr(stock, name) != getattr(adcp, name):
            mismatches.append(name)
    if stock.trial.repeat_index != adcp.trial.repeat_index:
        mismatches.append("trial.repeat_index")
    if stock.trial.seed != adcp.trial.seed:
        mismatches.append("trial.seed")
    if stock.agent == adcp.agent:
        mismatches.append("agent_not_distinct")
    if stock.outputs is not None or adcp.outputs is not None:
        mismatches.append("pre_execution_outputs")
    if mismatches:
        raise PairFairnessError("paired causal controls differ: " + ",".join(mismatches))


@dataclass(frozen=True, slots=True)
class ArmExecutionReceipt(CanonicalModel):
    arm: ExperimentArm
    manifest_identity: Sha256Digest
    status: str
    model_called: bool
    total_model_tokens: int = 0
    requests: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.arm, ExperimentArm):
            object.__setattr__(self, "arm", ExperimentArm(self.arm))
        if not isinstance(self.manifest_identity, Sha256Digest):
            object.__setattr__(self, "manifest_identity", Sha256Digest(str(self.manifest_identity)))
        require_identifier(self.status, "status")
        if not isinstance(self.model_called, bool):
            raise ValueError("model_called must be boolean")
        _non_negative_int(self.total_model_tokens, "total_model_tokens")
        _non_negative_int(self.requests, "requests")
        if not self.model_called and (self.total_model_tokens != 0 or self.requests != 0):
            raise ValueError("no-model receipt cannot report model usage")


@dataclass(frozen=True, slots=True)
class PairedRunReceipt(CanonicalModel):
    pair_identity: Sha256Digest
    execution_order: tuple[ExperimentArm, ExperimentArm]
    paid: bool
    admission_identity: Sha256Digest | None
    arm_receipts: tuple[ArmExecutionReceipt, ArmExecutionReceipt]

    def __post_init__(self) -> None:
        if not isinstance(self.pair_identity, Sha256Digest):
            object.__setattr__(self, "pair_identity", Sha256Digest(str(self.pair_identity)))
        order = tuple(item if isinstance(item, ExperimentArm) else ExperimentArm(item) for item in self.execution_order)
        if len(order) != 2 or set(order) != {ExperimentArm.STOCK, ExperimentArm.ADCP}:
            raise ValueError("execution_order must contain Stock and ADCP exactly once")
        object.__setattr__(self, "execution_order", order)
        if not isinstance(self.paid, bool):
            raise ValueError("paid must be boolean")
        if self.admission_identity is not None and not isinstance(self.admission_identity, Sha256Digest):
            object.__setattr__(self, "admission_identity", Sha256Digest(str(self.admission_identity)))
        receipts = tuple(self.arm_receipts)
        if len(receipts) != 2 or {item.arm for item in receipts} != {ExperimentArm.STOCK, ExperimentArm.ADCP}:
            raise ValueError("pair receipt requires exactly one receipt per arm")
        object.__setattr__(self, "arm_receipts", receipts)


@runtime_checkable
class PairedArmExecutor(Protocol):
    def execute(self, manifest: ExperimentManifest, arm: ExperimentArm) -> ArmExecutionReceipt:
        """Execute one already-admitted atomic arm and return exact accounting."""


class PairedExperimentController:
    """Execute the two arms in precommitted deterministic randomized order."""

    def run(
        self,
        plan: PairedExperimentPlan,
        executors: Mapping[ExperimentArm, PairedArmExecutor],
        *,
        paid: bool,
        admission: PaidAdmissionSnapshot | None = None,
    ) -> PairedRunReceipt:
        manifests = plan.manifests()
        missing = set(ExperimentArm) - set(executors)
        if missing:
            raise ValueError("missing arm executor(s): " + ",".join(sorted(arm.value for arm in missing)))

        admission_identity: Sha256Digest | None = None
        if paid:
            if admission is None:
                raise PaidExperimentBlocked("paid execution requires an admission snapshot")
            admission.require_paid_ready(plan)
            admission_identity = admission.content_digest

        receipts: list[ArmExecutionReceipt] = []
        for arm in plan.arm_order:
            manifest = manifests[arm]
            receipt = executors[arm].execute(manifest, arm)
            if receipt.arm is not arm:
                raise PairFairnessError("executor returned receipt for the wrong arm")
            if receipt.manifest_identity != manifest.identity:
                raise PairFairnessError("executor receipt does not bind the planned manifest identity")
            if not paid and receipt.model_called:
                raise DryRunModelCallForbidden("dry-run arm attempted a model call")
            receipts.append(receipt)

        return PairedRunReceipt(
            pair_identity=plan.pair_identity,
            execution_order=plan.arm_order,
            paid=paid,
            admission_identity=admission_identity,
            arm_receipts=(receipts[0], receipts[1]),
        )
