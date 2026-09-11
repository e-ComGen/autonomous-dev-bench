"""Durable outcome-blind execution substrate for the locked Phase 3D campaign.

This module owns *campaign* durability only.  It deliberately does not know how
Harbor, DeepSeek, ADCP or the official SWE-bench evaluator are implemented.  A
pair executor supplies one arm artifact at a time and a grader supplies one
official boolean outcome at a time.

Safety properties:

* paid execution is impossible without an explicit caller authorization bit;
* repository admission is re-checked before any executor invocation;
* the locked deterministic arm order is preserved across crashes;
* a durable completed first arm is reused when the process dies before arm two;
* a crash after an arm is marked RUNNING but before its durable artifact exists
  becomes ``experiment_accounting_unknown`` and the attempt is excluded;
* grader crashes are safe to retry because grading performs no model calls;
* only complete pairs are added as included outcomes;
* progress reporting never exposes treatment effect, per-arm win counts,
  p-values or a winner before the complete schedule exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from .experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ModelManifest,
    TaskManifest,
)
from .identity import Sha256Digest, canonical_json
from .paired_analysis import (
    ExclusionReason,
    PairOutcomeAttempt,
    PairScheduleEntry,
    PairedExperimentSchedule,
    audit_paired_ledger,
)
from .paired_experiment import (
    ArmExecutionReceipt,
    ExperimentArm,
    PaidAdmissionSnapshot,
    PaidExperimentBlocked,
    PairedExperimentPlan,
)


CAMPAIGN_SCOPE = "PHASE3D_DURABLE_PAIRED_CAMPAIGN_V1"
LEDGER_SCHEMA_VERSION = 1


class Phase3DCampaignError(RuntimeError):
    """Campaign state or execution violates a locked invariant."""


class PaidCampaignAuthorizationRequired(Phase3DCampaignError):
    """No paid arm may start without an explicit operator authorization."""


class CampaignRecoveryRequired(Phase3DCampaignError):
    """A durable recovery boundary was recorded; rerun to continue safely."""


class PreDispatchInfrastructureFailure(Phase3DCampaignError):
    """The arm executor proves no model dispatch happened."""


class ExperimentAccountingUnknownFailure(Phase3DCampaignError):
    """The executor cannot prove whether all provider side effects were accounted."""


class OfficialGraderInfrastructureFailure(Phase3DCampaignError):
    """Official grading failed without changing model-side evidence."""


@dataclass(frozen=True, slots=True)
class CampaignArmArtifact:
    receipt: ArmExecutionReceipt
    patch_sha256: Sha256Digest | str
    patch_bytes: int
    evidence_sha256: Sha256Digest | str

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ArmExecutionReceipt):
            raise TypeError("receipt must be ArmExecutionReceipt")
        if not isinstance(self.patch_sha256, Sha256Digest):
            object.__setattr__(self, "patch_sha256", Sha256Digest(str(self.patch_sha256)))
        if not isinstance(self.evidence_sha256, Sha256Digest):
            object.__setattr__(self, "evidence_sha256", Sha256Digest(str(self.evidence_sha256)))
        if isinstance(self.patch_bytes, bool) or not isinstance(self.patch_bytes, int) or self.patch_bytes < 0:
            raise ValueError("patch_bytes must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "arm": self.receipt.arm.value,
            "manifest_identity": str(self.receipt.manifest_identity),
            "status": self.receipt.status,
            "model_called": self.receipt.model_called,
            "total_model_tokens": self.receipt.total_model_tokens,
            "requests": self.receipt.requests,
            "patch_sha256": str(self.patch_sha256),
            "patch_bytes": self.patch_bytes,
            "evidence_sha256": str(self.evidence_sha256),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "CampaignArmArtifact":
        return cls(
            receipt=ArmExecutionReceipt(
                arm=ExperimentArm(str(raw["arm"])),
                manifest_identity=str(raw["manifest_identity"]),
                status=str(raw["status"]),
                model_called=raw["model_called"],
                total_model_tokens=raw["total_model_tokens"],
                requests=raw["requests"],
            ),
            patch_sha256=str(raw["patch_sha256"]),
            patch_bytes=raw["patch_bytes"],
            evidence_sha256=str(raw["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class OfficialGradeArtifact:
    resolved: bool
    evidence_sha256: Sha256Digest | str

    def __post_init__(self) -> None:
        if not isinstance(self.resolved, bool):
            raise ValueError("official resolved outcome must be boolean")
        if not isinstance(self.evidence_sha256, Sha256Digest):
            object.__setattr__(self, "evidence_sha256", Sha256Digest(str(self.evidence_sha256)))

    def to_dict(self) -> dict[str, object]:
        return {"resolved": self.resolved, "evidence_sha256": str(self.evidence_sha256)}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "OfficialGradeArtifact":
        return cls(resolved=raw["resolved"], evidence_sha256=str(raw["evidence_sha256"]))


@dataclass(frozen=True, slots=True)
class CampaignProgress:
    expected_pairs: int
    completed_pairs: int
    excluded_attempts: int
    missing_pairs: int
    complete: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "scope": "PHASE3D_CAMPAIGN_PROGRESS_OUTCOME_BLIND",
            "expected_pairs": self.expected_pairs,
            "completed_pairs": self.completed_pairs,
            "excluded_attempts": self.excluded_attempts,
            "missing_pairs": self.missing_pairs,
            "complete": self.complete,
            "treatment_effect_exposed": False,
            "p_value_exposed": False,
            "winner_exposed": False,
        }


class CampaignPairExecutor(Protocol):
    def execute_arm(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        attempt_dir: Path,
    ) -> CampaignArmArtifact: ...


class CampaignOfficialGrader(Protocol):
    def grade_arm(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        artifact: CampaignArmArtifact,
        attempt_dir: Path,
    ) -> OfficialGradeArtifact: ...


class PairPlanFactory(Protocol):
    def __call__(self, entry: PairScheduleEntry) -> PairedExperimentPlan: ...


def materialize_pair_plan(
    admission: PaidAdmissionSnapshot,
    entry: PairScheduleEntry,
    *,
    environment_image_digest: str,
) -> PairedExperimentPlan:
    """Materialize one runtime pair directly from the locked admission design."""
    design = admission.experiment_design
    if not design.design_paid_ready:
        raise PaidExperimentBlocked("experiment design is not paid-ready")
    required = {
        "input_token_cap_per_arm": design.input_token_cap_per_arm,
        "output_token_cap_per_arm": design.output_token_cap_per_arm,
        "total_model_token_cap_per_arm": design.total_model_token_cap_per_arm,
        "max_requests_per_arm": design.max_requests_per_arm,
        "wall_time_seconds_per_arm": design.wall_time_seconds_per_arm,
        "patch_byte_cap_per_arm": design.patch_byte_cap_per_arm,
    }
    if any(value is None for value in required.values()):
        raise PaidExperimentBlocked("locked paid design is missing runtime budget values")

    return PairedExperimentPlan(
        pair_id=entry.pair_id,
        task=TaskManifest(
            dataset=design.dataset,
            dataset_version=design.official_swebench_version,
            task_id=entry.task_id,
            task_repo_commit=design.task_repo_commit,
            environment_image_digest=environment_image_digest,
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
            configuration={"runtime": "packages.zone_development.ZoneDevelopmentRuntime"},
        ),
        model=ModelManifest(
            identifier=design.model,
            provider_route=design.provider,
            decoding={"temperature": 0},
        ),
        budget=BudgetManifest(
            input_token_cap=int(required["input_token_cap_per_arm"]),
            output_token_cap=int(required["output_token_cap_per_arm"]),
            total_model_token_cap=int(required["total_model_token_cap_per_arm"]),
            max_requests=int(required["max_requests_per_arm"]),
            wall_time_seconds=int(required["wall_time_seconds_per_arm"]),
            patch_byte_cap=int(required["patch_byte_cap_per_arm"]),
        ),
        execution=ExecutionManifest(
            engine="harbor",
            engine_version=design.harbor_version,
            provider=design.environment_provider,
            network_policy="task_policy",
            resource_policy={"fresh_independent_environment_per_arm": True},
        ),
        repeat_index=entry.repeat_index,
        seed=entry.seed,
        order_algorithm=design.pair_order_algorithm,
    )


class DurablePhase3DCampaign:
    """Crash-safe campaign loop over the immutable paired schedule."""

    def __init__(
        self,
        *,
        repository_root: Path,
        workspace: Path,
        expected_benchmark_commit: str,
        admission: PaidAdmissionSnapshot,
        schedule: PairedExperimentSchedule,
        plan_factory: PairPlanFactory,
        executor: CampaignPairExecutor,
        grader: CampaignOfficialGrader,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.workspace = workspace.resolve()
        self.expected_benchmark_commit = expected_benchmark_commit
        self.admission = admission
        self.schedule = schedule
        self.plan_factory = plan_factory
        self.executor = executor
        self.grader = grader
        self.ledger_path = self.workspace / "paired-ledger.json"
        self.campaign_path = self.workspace / "campaign.json"
        self.pairs_root = self.workspace / "pairs"

    def run(
        self,
        *,
        paid_authorized: bool,
        max_new_pairs: int | None = None,
    ) -> CampaignProgress:
        # This is intentionally the first dynamic gate.  Merely constructing a
        # runner, importing this module or asking for progress cannot invoke an arm.
        if paid_authorized is not True:
            raise PaidCampaignAuthorizationRequired(
                "explicit paid campaign authorization is required before any arm execution"
            )
        if max_new_pairs is not None and (
            isinstance(max_new_pairs, bool) or not isinstance(max_new_pairs, int) or max_new_pairs <= 0
        ):
            raise ValueError("max_new_pairs must be a positive integer or null")

        self._require_exact_repository_commit()
        if not self.admission.paid_ready:
            raise PaidExperimentBlocked("paid admission is not ready: " + ",".join(self.admission.blockers))
        self._initialize_or_validate_campaign()
        ledger = self._load_ledger()
        completed_before = set(self._completed_pair_ids(ledger))
        new_pairs = 0

        for entry in self.schedule.entries:
            if entry.pair_id in completed_before:
                continue
            if max_new_pairs is not None and new_pairs >= max_new_pairs:
                break
            self._run_pair(entry)
            ledger = self._load_ledger()
            completed_now = set(self._completed_pair_ids(ledger))
            if entry.pair_id in completed_now:
                completed_before = completed_now
                new_pairs += 1

        return self.progress()

    def progress(self) -> CampaignProgress:
        self._initialize_or_validate_campaign()
        ledger = self._load_ledger()
        attempts = tuple(_parse_outcome_attempt(item) for item in ledger["attempts"])
        audit = audit_paired_ledger(self.schedule, attempts)
        return CampaignProgress(
            expected_pairs=audit.expected_pairs,
            completed_pairs=audit.completed_pairs,
            excluded_attempts=audit.excluded_attempts,
            missing_pairs=len(audit.missing_pair_ids),
            complete=audit.complete,
        )

    def _run_pair(self, entry: PairScheduleEntry) -> None:
        attempt_dir, attempt_index, attempt = self._active_attempt(entry)
        plan = self.plan_factory(entry)
        self.admission.require_paid_ready(plan)
        if plan.pair_id != entry.pair_id or plan.repeat_index != entry.repeat_index or plan.seed != entry.seed:
            raise Phase3DCampaignError("plan factory drifted from locked schedule identity")
        manifests = plan.manifests()
        expected_plan_identity = str(plan.pair_identity)
        expected_order = [arm.value for arm in plan.arm_order]

        if attempt is None:
            attempt = {
                "schema_version": 1,
                "pair_id": entry.pair_id,
                "task_id": entry.task_id,
                "repeat_index": entry.repeat_index,
                "seed": entry.seed,
                "attempt_index": attempt_index,
                "pair_identity": expected_plan_identity,
                "execution_order": expected_order,
                "status": "ACTIVE",
                "running_arm": None,
                "running_grader": None,
            }
            attempt_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write_json(attempt_dir / "attempt.json", attempt)
        else:
            self._validate_attempt_header(attempt, entry, attempt_index, expected_plan_identity, expected_order)
            running_arm = attempt.get("running_arm")
            if attempt.get("status") == "RUNNING_ARM" and isinstance(running_arm, str):
                artifact_path = attempt_dir / f"arm-{running_arm}.json"
                if not artifact_path.is_file():
                    self._exclude_attempt(
                        entry,
                        plan,
                        attempt_dir,
                        attempt_index,
                        ExclusionReason.EXPERIMENT_ACCOUNTING_UNKNOWN,
                        {
                            "cause": "resume_found_running_arm_without_durable_artifact",
                            "arm": running_arm,
                        },
                    )
                    raise CampaignRecoveryRequired(
                        f"{entry.pair_id} attempt {attempt_index} excluded: model accounting may be unknown; rerun to start next attempt"
                    )
                attempt["status"] = "ACTIVE"
                attempt["running_arm"] = None
                _atomic_write_json(attempt_dir / "attempt.json", attempt)
            elif attempt.get("status") == "RUNNING_GRADER":
                # Official grading is model-free and therefore safe to replay.
                attempt["status"] = "ACTIVE"
                attempt["running_grader"] = None
                _atomic_write_json(attempt_dir / "attempt.json", attempt)

        arm_artifacts: dict[ExperimentArm, CampaignArmArtifact] = {}
        for arm in plan.arm_order:
            path = attempt_dir / f"arm-{arm.value}.json"
            if path.is_file():
                artifact = CampaignArmArtifact.from_dict(_read_object(path))
                self._validate_arm_artifact(plan, arm, artifact)
                arm_artifacts[arm] = artifact
                continue

            attempt["status"] = "RUNNING_ARM"
            attempt["running_arm"] = arm.value
            _atomic_write_json(attempt_dir / "attempt.json", attempt)
            try:
                artifact = self.executor.execute_arm(plan, arm, attempt_dir)
            except PreDispatchInfrastructureFailure as error:
                self._exclude_attempt(
                    entry,
                    plan,
                    attempt_dir,
                    attempt_index,
                    ExclusionReason.PRE_DISPATCH_INFRASTRUCTURE_FAILURE,
                    {"cause": type(error).__name__, "detail": str(error), "arm": arm.value},
                )
                raise CampaignRecoveryRequired(
                    f"{entry.pair_id} attempt {attempt_index} excluded before dispatch; rerun to start next attempt"
                ) from error
            except ExperimentAccountingUnknownFailure as error:
                self._exclude_attempt(
                    entry,
                    plan,
                    attempt_dir,
                    attempt_index,
                    ExclusionReason.EXPERIMENT_ACCOUNTING_UNKNOWN,
                    {"cause": type(error).__name__, "detail": str(error), "arm": arm.value},
                )
                raise CampaignRecoveryRequired(
                    f"{entry.pair_id} attempt {attempt_index} excluded for unknown accounting; rerun to start next attempt"
                ) from error
            except BaseException as error:
                # Once RUNNING_ARM is durable, an unclassified failure must be
                # treated as possibly post-dispatch.  Never silently retry it.
                self._exclude_attempt(
                    entry,
                    plan,
                    attempt_dir,
                    attempt_index,
                    ExclusionReason.EXPERIMENT_ACCOUNTING_UNKNOWN,
                    {"cause": type(error).__name__, "detail": str(error), "arm": arm.value},
                )
                raise CampaignRecoveryRequired(
                    f"{entry.pair_id} attempt {attempt_index} excluded after unclassified arm failure"
                ) from error

            self._validate_arm_artifact(plan, arm, artifact)
            _atomic_write_json(path, artifact.to_dict())
            arm_artifacts[arm] = artifact
            attempt["status"] = "ACTIVE"
            attempt["running_arm"] = None
            _atomic_write_json(attempt_dir / "attempt.json", attempt)

        grades: dict[ExperimentArm, OfficialGradeArtifact] = {}
        for arm in (ExperimentArm.STOCK, ExperimentArm.ADCP):
            path = attempt_dir / f"grade-{arm.value}.json"
            if path.is_file():
                grades[arm] = OfficialGradeArtifact.from_dict(_read_object(path))
                continue
            attempt["status"] = "RUNNING_GRADER"
            attempt["running_grader"] = arm.value
            _atomic_write_json(attempt_dir / "attempt.json", attempt)
            try:
                grade = self.grader.grade_arm(plan, arm, arm_artifacts[arm], attempt_dir)
            except BaseException as error:
                failure = {
                    "schema_version": 1,
                    "scope": "PHASE3D_OFFICIAL_GRADER_RETRY_EVIDENCE",
                    "pair_id": entry.pair_id,
                    "attempt_index": attempt_index,
                    "arm": arm.value,
                    "cause": type(error).__name__,
                    "detail": str(error),
                    "model_called": False,
                }
                _atomic_write_json(attempt_dir / f"grader-retry-{arm.value}.json", failure)
                attempt["status"] = "GRADER_RETRY_REQUIRED"
                attempt["running_grader"] = arm.value
                _atomic_write_json(attempt_dir / "attempt.json", attempt)
                raise OfficialGraderInfrastructureFailure(
                    f"official grader failed for {entry.pair_id}/{arm.value}; paid arms are preserved and grader may be retried"
                ) from error
            _atomic_write_json(path, grade.to_dict())
            grades[arm] = grade
            attempt["status"] = "ACTIVE"
            attempt["running_grader"] = None
            _atomic_write_json(attempt_dir / "attempt.json", attempt)

        outcome = PairOutcomeAttempt(
            pair_id=entry.pair_id,
            task_id=entry.task_id,
            repeat_index=entry.repeat_index,
            seed=entry.seed,
            attempt_index=attempt_index,
            stock_manifest_identity=manifests[ExperimentArm.STOCK].identity,
            adcp_manifest_identity=manifests[ExperimentArm.ADCP].identity,
            stock_resolved=grades[ExperimentArm.STOCK].resolved,
            adcp_resolved=grades[ExperimentArm.ADCP].resolved,
            stock_grader_evidence=grades[ExperimentArm.STOCK].evidence_sha256,
            adcp_grader_evidence=grades[ExperimentArm.ADCP].evidence_sha256,
        )
        self._append_outcome(outcome)
        attempt["status"] = "COMPLETED"
        attempt["running_arm"] = None
        attempt["running_grader"] = None
        _atomic_write_json(attempt_dir / "attempt.json", attempt)

    def _active_attempt(
        self, entry: PairScheduleEntry
    ) -> tuple[Path, int, dict[str, object] | None]:
        pair_dir = self.pairs_root / entry.pair_id
        pair_dir.mkdir(parents=True, exist_ok=True)
        candidates = sorted(pair_dir.glob("attempt-*"))
        if not candidates:
            return pair_dir / "attempt-0000", 0, None
        last = candidates[-1]
        try:
            index = int(last.name.removeprefix("attempt-"))
        except ValueError as error:
            raise Phase3DCampaignError(f"invalid attempt directory: {last}") from error
        state_path = last / "attempt.json"
        if not state_path.is_file():
            # Directory creation without its first atomic state cannot have
            # crossed an executor boundary; discard the empty shell safely.
            if any(last.iterdir()):
                raise Phase3DCampaignError(f"attempt directory lacks state but is not empty: {last}")
            last.rmdir()
            return pair_dir / f"attempt-{index:04d}", index, None
        attempt = _read_object(state_path)
        status = attempt.get("status")
        if status in {"COMPLETED", "EXCLUDED"}:
            return pair_dir / f"attempt-{index + 1:04d}", index + 1, None
        return last, index, attempt

    def _validate_attempt_header(
        self,
        attempt: dict[str, object],
        entry: PairScheduleEntry,
        attempt_index: int,
        pair_identity: str,
        execution_order: list[str],
    ) -> None:
        expected = {
            "pair_id": entry.pair_id,
            "task_id": entry.task_id,
            "repeat_index": entry.repeat_index,
            "seed": entry.seed,
            "attempt_index": attempt_index,
            "pair_identity": pair_identity,
            "execution_order": execution_order,
        }
        mismatches = [name for name, value in expected.items() if attempt.get(name) != value]
        if mismatches:
            raise Phase3DCampaignError("durable attempt identity drift: " + ",".join(mismatches))

    def _validate_arm_artifact(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        artifact: CampaignArmArtifact,
    ) -> None:
        manifest = plan.manifest_for(arm)
        receipt = artifact.receipt
        if receipt.arm is not arm:
            raise Phase3DCampaignError("arm artifact reports wrong arm")
        if receipt.manifest_identity != manifest.identity:
            raise Phase3DCampaignError("arm artifact manifest identity differs from locked plan")
        if artifact.patch_bytes > plan.budget.patch_byte_cap:
            raise Phase3DCampaignError("arm patch exceeds locked patch byte cap")

    def _exclude_attempt(
        self,
        entry: PairScheduleEntry,
        plan: PairedExperimentPlan,
        attempt_dir: Path,
        attempt_index: int,
        reason: ExclusionReason,
        detail: dict[str, object],
    ) -> None:
        evidence = {
            "schema_version": 1,
            "scope": "PHASE3D_EXCLUDED_ATTEMPT_EVIDENCE",
            "pair_id": entry.pair_id,
            "task_id": entry.task_id,
            "repeat_index": entry.repeat_index,
            "seed": entry.seed,
            "attempt_index": attempt_index,
            "reason": reason.value,
            "detail": detail,
        }
        evidence_digest = Sha256Digest.of(evidence)
        _atomic_write_json(attempt_dir / "exclusion.json", evidence)
        manifests = plan.manifests()
        outcome = PairOutcomeAttempt(
            pair_id=entry.pair_id,
            task_id=entry.task_id,
            repeat_index=entry.repeat_index,
            seed=entry.seed,
            attempt_index=attempt_index,
            stock_manifest_identity=manifests[ExperimentArm.STOCK].identity,
            adcp_manifest_identity=manifests[ExperimentArm.ADCP].identity,
            stock_resolved=None,
            adcp_resolved=None,
            exclusion_reason=reason,
            exclusion_evidence=evidence_digest,
        )
        self._append_outcome(outcome)
        attempt_path = attempt_dir / "attempt.json"
        attempt = _read_object(attempt_path) if attempt_path.is_file() else {
            "schema_version": 1,
            "pair_id": entry.pair_id,
            "task_id": entry.task_id,
            "repeat_index": entry.repeat_index,
            "seed": entry.seed,
            "attempt_index": attempt_index,
            "pair_identity": str(plan.pair_identity),
            "execution_order": [arm.value for arm in plan.arm_order],
        }
        attempt["status"] = "EXCLUDED"
        attempt["exclusion_reason"] = reason.value
        attempt["running_arm"] = None
        attempt["running_grader"] = None
        _atomic_write_json(attempt_path, attempt)

    def _append_outcome(self, outcome: PairOutcomeAttempt) -> None:
        ledger = self._load_ledger()
        attempts = list(ledger["attempts"])
        key = (outcome.pair_id, outcome.attempt_index)
        for raw in attempts:
            if (raw.get("pair_id"), raw.get("attempt_index")) == key:
                existing = _parse_outcome_attempt(raw)
                if existing.to_canonical_json() != outcome.to_canonical_json():
                    raise Phase3DCampaignError("attempt ledger identity already exists with different evidence")
                return
        attempts.append(_outcome_payload(outcome))
        parsed = tuple(_parse_outcome_attempt(item) for item in attempts)
        audit_paired_ledger(self.schedule, parsed)
        ledger["attempts"] = attempts
        _atomic_write_json(self.ledger_path, ledger)

    def _completed_pair_ids(self, ledger: dict[str, object]) -> tuple[str, ...]:
        attempts = tuple(_parse_outcome_attempt(item) for item in ledger["attempts"])
        included = {item.pair_id for item in attempts if item.included}
        return tuple(entry.pair_id for entry in self.schedule.entries if entry.pair_id in included)

    def _initialize_or_validate_campaign(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.pairs_root.mkdir(parents=True, exist_ok=True)
        expected_campaign = {
            "schema_version": 1,
            "scope": CAMPAIGN_SCOPE,
            "benchmark_commit": self.expected_benchmark_commit,
            "admission_identity": str(self.admission.content_digest),
            "design_identity": str(self.admission.experiment_design.plan_digest),
            "schedule_identity": str(self.schedule.content_digest),
            "pair_count": len(self.schedule.entries),
            "interim_outcome_statistics_allowed": False,
        }
        if not self.campaign_path.is_file():
            _atomic_write_json(self.campaign_path, expected_campaign)
        elif _read_object(self.campaign_path) != expected_campaign:
            raise Phase3DCampaignError("campaign workspace belongs to a different immutable experiment")

        expected_ledger = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "design_identity": str(self.admission.experiment_design.plan_digest),
            "attempts": [],
        }
        if not self.ledger_path.is_file():
            _atomic_write_json(self.ledger_path, expected_ledger)
        else:
            ledger = self._load_ledger()
            if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
                raise Phase3DCampaignError("unsupported paired ledger schema")
            if ledger.get("design_identity") != expected_ledger["design_identity"]:
                raise Phase3DCampaignError("paired ledger is bound to a different design")

    def _load_ledger(self) -> dict[str, object]:
        if not self.ledger_path.is_file():
            return {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "design_identity": str(self.admission.experiment_design.plan_digest),
                "attempts": [],
            }
        raw = _read_object(self.ledger_path)
        if set(raw) != {"schema_version", "design_identity", "attempts"}:
            raise Phase3DCampaignError("paired ledger fields differ from analyzer contract")
        if not isinstance(raw.get("attempts"), list):
            raise Phase3DCampaignError("paired ledger attempts must be a list")
        return raw

    def _require_exact_repository_commit(self) -> None:
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(self.repository_root), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        observed = completed.stdout.strip().lower()
        if completed.returncode != 0 or observed != self.expected_benchmark_commit.lower():
            raise Phase3DCampaignError(
                f"campaign checkout mismatch: expected {self.expected_benchmark_commit}, observed {observed or '<unavailable>'}"
            )


def _outcome_payload(outcome: PairOutcomeAttempt) -> dict[str, object]:
    """Plain-JSON ledger row.

    Canonical model JSON nests a ``Sha256Digest`` as ``{"value": ...}``, which
    :func:`_parse_outcome_attempt` cannot read back. The ledger is written with
    digest and reason values as their canonical strings so the round trip is
    lossless.
    """

    return {
        "pair_id": outcome.pair_id,
        "task_id": outcome.task_id,
        "repeat_index": outcome.repeat_index,
        "seed": outcome.seed,
        "attempt_index": outcome.attempt_index,
        "stock_manifest_identity": str(outcome.stock_manifest_identity),
        "adcp_manifest_identity": str(outcome.adcp_manifest_identity),
        "stock_resolved": outcome.stock_resolved,
        "adcp_resolved": outcome.adcp_resolved,
        "stock_grader_evidence": _digest_text(outcome.stock_grader_evidence),
        "adcp_grader_evidence": _digest_text(outcome.adcp_grader_evidence),
        "exclusion_reason": None if outcome.exclusion_reason is None else outcome.exclusion_reason.value,
        "exclusion_evidence": _digest_text(outcome.exclusion_evidence),
    }


def _digest_text(value: Sha256Digest | None) -> str | None:
    return None if value is None else str(value)


def _parse_outcome_attempt(raw: object) -> PairOutcomeAttempt:
    if not isinstance(raw, dict):
        raise Phase3DCampaignError("paired ledger attempt must be an object")
    exclusion_raw = raw.get("exclusion_reason")
    exclusion = None if exclusion_raw is None else ExclusionReason(str(exclusion_raw))
    return PairOutcomeAttempt(
        pair_id=raw["pair_id"],
        task_id=raw["task_id"],
        repeat_index=raw["repeat_index"],
        seed=raw["seed"],
        attempt_index=raw["attempt_index"],
        stock_manifest_identity=raw["stock_manifest_identity"],
        adcp_manifest_identity=raw["adcp_manifest_identity"],
        stock_resolved=raw.get("stock_resolved"),
        adcp_resolved=raw.get("adcp_resolved"),
        stock_grader_evidence=raw.get("stock_grader_evidence"),
        adcp_grader_evidence=raw.get("adcp_grader_evidence"),
        exclusion_reason=exclusion,
        exclusion_evidence=raw.get("exclusion_evidence"),
    )


def _read_object(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase3DCampaignError(f"cannot read durable campaign JSON: {path}") from error
    if not isinstance(raw, dict):
        raise Phase3DCampaignError(f"durable campaign JSON must be an object: {path}")
    return raw


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except (AttributeError, OSError):
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def sha256_bytes(value: bytes) -> Sha256Digest:
    return Sha256Digest("sha256:" + hashlib.sha256(value).hexdigest())


def canonical_evidence_digest(value: object) -> Sha256Digest:
    return sha256_bytes(canonical_json(value).encode("utf-8"))
