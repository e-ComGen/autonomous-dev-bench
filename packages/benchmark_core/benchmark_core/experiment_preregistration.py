"""Outcome-blind preregistration validator for the first paid paired experiment.

A scientific plan can be structurally valid while still incomplete. Structural
identity drift (cohort, treatment, model, Harbor pin, grading authority, causal
analysis shape) is an error. Cost/sample-size fields may remain unset while the
plan is a DRAFT, but those omissions become explicit paid-admission blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .identity import CanonicalModel, Sha256Digest


class ExperimentPlanInvalid(ValueError):
    """The preregistration contradicts accepted experiment identities/invariants."""


@dataclass(frozen=True, slots=True)
class ExperimentDesignSnapshot(CanonicalModel):
    status: str
    design_paid_ready: bool
    design_blockers: tuple[str, ...]
    task_count: int
    repeat_count_per_task: int | None
    required_completed_pairs: int | None
    total_model_token_cap_per_arm: int | None
    plan_digest: Sha256Digest
    cohort_source_digest: Sha256Digest
    stock_lock_digest: Sha256Digest
    adcp_lock_digest: Sha256Digest
    harbor_lock_digest: Sha256Digest

    def __post_init__(self) -> None:
        object.__setattr__(self, "design_blockers", tuple(self.design_blockers))
        for name in (
            "plan_digest",
            "cohort_source_digest",
            "stock_lock_digest",
            "adcp_lock_digest",
            "harbor_lock_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, Sha256Digest):
                object.__setattr__(self, name, Sha256Digest(str(value)))

    @classmethod
    def from_repository(cls, root: str | Path) -> "ExperimentDesignSnapshot":
        root_path = Path(root)
        plan = _read_object(root_path / "PHASE3D_EXPERIMENT_PLAN.json")
        cohort = _read_object(root_path / "migration" / "swebench_v5_verified_parity.json")
        stock = _read_object(root_path / "DEEPSEEK_HARNESS.lock.json")
        adcp = _read_object(root_path / "ADCP.lock.json")
        harbor = _read_object(root_path / "HARBOR.lock.json")

        _validate_fixed_identity(plan, cohort, stock, adcp, harbor)
        blockers, repeat_count, required_pairs, total_cap = _design_blockers(plan)
        expected_ready = plan.get("status") == "LOCKED" and not blockers

        declared_blockers = plan.get("design_blockers")
        if not isinstance(declared_blockers, list) or any(not isinstance(item, str) for item in declared_blockers):
            raise ExperimentPlanInvalid("design_blockers must be a string list")
        if tuple(declared_blockers) != blockers:
            raise ExperimentPlanInvalid(
                f"declared design blockers differ from computed blockers: declared={declared_blockers}, computed={list(blockers)}"
            )
        if plan.get("design_paid_ready") is not expected_ready:
            raise ExperimentPlanInvalid("design_paid_ready differs from computed plan readiness")

        tasks = _mapping(plan, "corpus").get("tasks")
        assert isinstance(tasks, list)  # validated by _validate_fixed_identity
        return cls(
            status=str(plan.get("status")),
            design_paid_ready=expected_ready,
            design_blockers=blockers,
            task_count=len(tasks),
            repeat_count_per_task=repeat_count,
            required_completed_pairs=required_pairs,
            total_model_token_cap_per_arm=total_cap,
            plan_digest=Sha256Digest.of(plan),
            cohort_source_digest=Sha256Digest.of(cohort),
            stock_lock_digest=Sha256Digest.of(stock),
            adcp_lock_digest=Sha256Digest.of(adcp),
            harbor_lock_digest=Sha256Digest.of(harbor),
        )


def _read_object(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentPlanInvalid(f"cannot read experiment design source: {path}") from error
    if not isinstance(raw, dict):
        raise ExperimentPlanInvalid(f"experiment design source is not an object: {path}")
    return raw


def _mapping(source: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = source.get(name)
    if not isinstance(value, Mapping):
        raise ExperimentPlanInvalid(f"{name} must be an object")
    return value


def _positive_optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExperimentPlanInvalid(f"{name} must be null or a positive integer")
    return value


def _validate_fixed_identity(
    plan: Mapping[str, object],
    cohort: Mapping[str, object],
    stock: Mapping[str, object],
    adcp: Mapping[str, object],
    harbor: Mapping[str, object],
) -> None:
    if plan.get("schema_version") != 1:
        raise ExperimentPlanInvalid("unsupported preregistration schema_version")
    if plan.get("scope") != "PHASE3D_FIRST_STOCK_VS_ADCP_PAIRED_EXPERIMENT":
        raise ExperimentPlanInvalid("unexpected preregistration scope")
    if plan.get("status") not in {"DRAFT_BLOCKED", "LOCKED"}:
        raise ExperimentPlanInvalid("status must be DRAFT_BLOCKED or LOCKED")

    treatment = _mapping(plan, "treatment")
    arm_a = _mapping(treatment, "arm_a")
    arm_b = _mapping(treatment, "arm_b")
    stock_ref = _mapping(stock, "qualification_reference")
    if arm_a.get("name") != "stock" or arm_a.get("implementation") != "stock_deepseek_harness":
        raise ExperimentPlanInvalid("Arm A identity changed")
    if arm_a.get("commit") != stock_ref.get("commit"):
        raise ExperimentPlanInvalid("Arm A commit differs from stock Harness lock")
    if arm_b.get("name") != "adcp" or arm_b.get("implementation") != "adcp_zone_development":
        raise ExperimentPlanInvalid("Arm B identity changed")
    if arm_b.get("commit") != adcp.get("commit"):
        raise ExperimentPlanInvalid("Arm B commit differs from ADCP lock")
    if arm_b.get("runtime") != adcp.get("runtime") or arm_b.get("integration") != adcp.get("integration"):
        raise ExperimentPlanInvalid("Arm B runtime/integration differs from ADCP lock")
    if treatment.get("model") != stock.get("model") or treatment.get("model") != adcp.get("model_route"):
        raise ExperimentPlanInvalid("experiment model differs from accepted arm locks")
    if treatment.get("provider") != stock.get("provider") or treatment.get("provider") != adcp.get("provider_route"):
        raise ExperimentPlanInvalid("experiment provider differs from accepted arm locks")
    if treatment.get("intended_difference") != "agent_orchestration_only":
        raise ExperimentPlanInvalid("treatment must remain agent_orchestration_only")

    corpus = _mapping(plan, "corpus")
    official = _mapping(cohort, "official_swebench")
    task_repo = _mapping(cohort, "task_repo")
    expected_tasks = cohort.get("tasks")
    tasks = corpus.get("tasks")
    if not isinstance(expected_tasks, list) or not all(isinstance(item, str) for item in expected_tasks):
        raise ExperimentPlanInvalid("accepted cohort manifest has invalid task list")
    if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
        raise ExperimentPlanInvalid("preregistered corpus tasks must be a string list")
    if tasks != expected_tasks:
        raise ExperimentPlanInvalid("preregistered task cohort differs from accepted Phase 1 cohort")
    if len(tasks) != len(set(tasks)):
        raise ExperimentPlanInvalid("preregistered task cohort contains duplicates")
    if corpus.get("dataset") != cohort.get("dataset"):
        raise ExperimentPlanInvalid("dataset identity differs from accepted cohort")
    if corpus.get("official_swebench_version") != official.get("version"):
        raise ExperimentPlanInvalid("official SWE-bench version differs from accepted cohort")
    if corpus.get("task_repo") != task_repo.get("repository") or corpus.get("task_repo_commit") != task_repo.get("commit"):
        raise ExperimentPlanInvalid("task repository identity differs from accepted cohort")
    if corpus.get("source_manifest") != "migration/swebench_v5_verified_parity.json":
        raise ExperimentPlanInvalid("corpus source_manifest changed")

    execution = _mapping(plan, "execution")
    if execution.get("substrate") != "harbor":
        raise ExperimentPlanInvalid("execution substrate must remain Harbor")
    if execution.get("harbor_version") != harbor.get("version") or execution.get("harbor_commit") != harbor.get("commit"):
        raise ExperimentPlanInvalid("Harbor identity differs from HARBOR.lock.json")
    if execution.get("environment_provider") != "docker":
        raise ExperimentPlanInvalid("first paired experiment provider must remain docker")
    if execution.get("official_grading_authority") != "swebench-v5":
        raise ExperimentPlanInvalid("official grading authority must remain swebench-v5")
    if execution.get("pair_order_algorithm") != "sha256-parity-v1":
        raise ExperimentPlanInvalid("pair ordering algorithm differs from accepted controller")
    seed = execution.get("master_seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ExperimentPlanInvalid("master_seed must be a non-negative integer")
    if execution.get("workspace_policy") != "fresh_independent_environment_per_arm":
        raise ExperimentPlanInvalid("each arm must receive a fresh independent environment")
    if execution.get("cross_arm_mutable_state_reuse") is not False:
        raise ExperimentPlanInvalid("cross-arm mutable state reuse is forbidden")

    budget = _mapping(plan, "budget")
    if budget.get("primary_fairness_measure") != "total_model_tokens":
        raise ExperimentPlanInvalid("primary fairness measure must remain total_model_tokens")
    secondary = budget.get("secondary_accounting")
    required_secondary = {
        "input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens",
        "requests", "cost_usd", "wall_time_ms",
    }
    if not isinstance(secondary, list) or set(secondary) != required_secondary:
        raise ExperimentPlanInvalid("secondary accounting fields changed")

    outcomes = _mapping(plan, "outcomes")
    if outcomes.get("primary_endpoint") != "official_swebench_v5_resolved":
        raise ExperimentPlanInvalid("primary endpoint changed")
    if outcomes.get("primary_estimand") != "paired_difference_in_resolution_rate_adcp_minus_stock":
        raise ExperimentPlanInvalid("primary estimand changed")

    analysis = _mapping(plan, "analysis")
    required_true = (
        "paired", "report_discordant_pairs", "report_per_task_results",
        "report_aggregate_resolution_rate", "report_primary_paired_effect",
        "no_universal_weighted_score", "outcome_blind_plan_changes_required",
    )
    if analysis.get("unit") != "task_repeat_pair" or any(analysis.get(name) is not True for name in required_true):
        raise ExperimentPlanInvalid("paired analysis invariants changed")

    exclusions = _mapping(plan, "exclusions")
    forbidden = exclusions.get("forbidden")
    if not isinstance(forbidden, list) or "exclude_because_result_hurts_hypothesis" not in forbidden:
        raise ExperimentPlanInvalid("outcome-based exclusion prohibition is missing")

    stopping = _mapping(plan, "stopping")
    if stopping.get("rule") != "fixed_precommitted_pairs_only" or stopping.get("interim_outcome_based_stopping") is not False:
        raise ExperimentPlanInvalid("stopping rule changed")


def _design_blockers(plan: Mapping[str, object]) -> tuple[tuple[str, ...], int | None, int | None, int | None]:
    execution = _mapping(plan, "execution")
    budget = _mapping(plan, "budget")
    stopping = _mapping(plan, "stopping")
    corpus = _mapping(plan, "corpus")
    tasks = corpus.get("tasks")
    assert isinstance(tasks, list)

    repeat_count = _positive_optional_int(execution.get("repeat_count_per_task"), "repeat_count_per_task")
    total_cap = _positive_optional_int(budget.get("total_model_token_cap_per_arm"), "total_model_token_cap_per_arm")
    input_cap = _positive_optional_int(budget.get("input_token_cap_per_arm"), "input_token_cap_per_arm")
    output_cap = _positive_optional_int(budget.get("output_token_cap_per_arm"), "output_token_cap_per_arm")
    max_requests = _positive_optional_int(budget.get("max_requests_per_arm"), "max_requests_per_arm")
    wall_time = _positive_optional_int(budget.get("wall_time_seconds_per_arm"), "wall_time_seconds_per_arm")
    patch_cap = _positive_optional_int(budget.get("patch_byte_cap_per_arm"), "patch_byte_cap_per_arm")
    required_pairs = _positive_optional_int(stopping.get("required_completed_pairs"), "required_completed_pairs")

    blockers: list[str] = []
    if plan.get("status") != "LOCKED":
        blockers.append("EXPERIMENT_PLAN_NOT_LOCKED")
    if repeat_count is None:
        blockers.append("REPEAT_COUNT_NOT_PRECOMMITTED")
    if total_cap is None:
        blockers.append("PRIMARY_TOKEN_BUDGET_NOT_PRECOMMITTED")
    if any(value is None for value in (input_cap, output_cap, max_requests, wall_time, patch_cap)):
        blockers.append("SECONDARY_RESOURCE_LIMITS_NOT_PRECOMMITTED")

    if repeat_count is not None:
        expected_pairs = len(tasks) * repeat_count
        if required_pairs is None:
            blockers.append("STOPPING_PAIR_COUNT_NOT_PRECOMMITTED")
        elif required_pairs != expected_pairs:
            raise ExperimentPlanInvalid(
                f"required_completed_pairs must equal task_count * repeat_count ({expected_pairs})"
            )
    elif required_pairs is not None:
        raise ExperimentPlanInvalid("required_completed_pairs cannot be set before repeat_count_per_task")

    if total_cap is not None and input_cap is not None and output_cap is not None:
        if total_cap < max(input_cap, output_cap):
            raise ExperimentPlanInvalid("total_model_token_cap_per_arm is inconsistent with component caps")

    return tuple(blockers), repeat_count, required_pairs, total_cap
