"""Operator-side real ADCP runner for one paid Phase 3D arm.

This file is copied into a locally built wrapper around the exact official
SWE-bench task image. It loads the pinned private ADCP source, constructs one
external DevelopmentWorkRequest from public task information, runs model-backed
Architect/Coder/Reviewer roles through the shared budget proxy, and exports a
candidate into the Harbor workspace only when ADCP returns CANDIDATE_READY.

No SWE-bench gold patch, test patch, FAIL_TO_PASS/PASS_TO_PASS list or official
outcome is read here. Final task correctness remains solely the official v5 grader.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterator


BENCH_ROOT = Path(os.environ.get("AUTOBENCH_BENCHMARK_SOURCE_ROOT", "/opt/autobench/benchmark")).resolve()
ADCP_ROOT = Path(os.environ.get("AUTOBENCH_ADCP_SOURCE_ROOT", "/opt/autobench/adcp")).resolve()
sys.path[:0] = [str(BENCH_ROOT), str(ADCP_ROOT), str(ADCP_ROOT / "packages" / "shared_contracts" / "src")]

from suites.coding.adcp_contract import (  # noqa: E402
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_MODEL_ROUTE,
    ADCP_PROVIDER_ROUTE,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
)
from suites.coding.adcp_dsh_binding import (  # noqa: E402
    DSH_BINDING_ID,
    DeepSeekHarnessBinding,
    DeepSeekHarnessProtocol,
    DeepSeekRoleCommand,
)
from suites.coding.phase3d_adcp_contract import PHASE3D_ADCP_RECEIPT_SCHEMA  # noqa: E402
from suites.coding.scope_projection import project_task_scope  # noqa: E402

import shared_contracts as sc  # noqa: E402
from packages import ecacc  # noqa: E402
from packages.harness_bridge.contracts import ContextBinding  # noqa: E402
from packages.harness_bridge.gateway import HarnessGateway  # noqa: E402
from packages.harness_bridge.journal import ExchangeJournal  # noqa: E402
from packages.harness_bridge.zone import HarnessCoder, HarnessLocalArchitect, HarnessReviewer  # noqa: E402
from packages.zone_development import (  # noqa: E402
    DevelopmentOutcome,
    DevelopmentWorkRequest,
    ECACCVerifier,
    OutcomeStatus,
    ReadScope,
    Role,
    RoleIdentity,
    RoleServices,
    SessionJournal,
    SessionLimits,
    WriteScope,
    ZoneDevelopmentRuntime,
)
from packages.zone_development import wire as zone_wire  # noqa: E402
from packages.zone_development.workspace import GitWorkspace  # noqa: E402


FIXED_TIMESTAMP = "2026-09-10T00:00:00.000000Z"
SCOPE_MAX_WRITE_PATHS = 512
SCOPE_MAX_READ_PATHS = 16
SCOPE_MAX_READ_BYTES = 32768


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def git(root: Path, *args: str, input_bytes: bytes | None = None, ok=(0,)) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    completed = subprocess.run(
        ["git", "-C", str(root), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=60,
        check=False,
    )
    if completed.returncode not in ok:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            + completed.stderr.decode("utf-8", "replace")[-3000:]
        )
    return completed.stdout.decode("utf-8", "replace")


def _safe_component(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _validate_target_identity() -> None:
    expected = {
        "repository": ADCP_REPOSITORY,
        "commit": ADCP_COMMIT,
        "runtime": ADCP_RUNTIME,
        "integration": ADCP_INTEGRATION,
    }
    observed = {
        "repository": required_env("AUTOBENCH_ADCP_TARGET_REPOSITORY"),
        "commit": required_env("AUTOBENCH_ADCP_TARGET_COMMIT"),
        "runtime": required_env("AUTOBENCH_ADCP_TARGET_RUNTIME"),
        "integration": required_env("AUTOBENCH_ADCP_TARGET_INTEGRATION"),
    }
    if observed != expected:
        raise ValueError(f"ADCP target identity drift: expected={expected}, observed={observed}")
    if required_env("AUTOBENCH_ADCP_MODEL") != ADCP_MODEL_ROUTE:
        raise ValueError("ADCP model route drift")
    if required_env("AUTOBENCH_ADCP_PROVIDER") != ADCP_PROVIDER_ROUTE:
        raise ValueError("ADCP provider route drift")
    if required_env("AUTOBENCH_MODEL_PROXY_MODE") != "1":
        raise ValueError("real ADCP run requires the shared model budget proxy")
    if os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"):
        raise ValueError("ADCP process unexpectedly possesses an upstream provider credential")
    if not ADCP_ROOT.joinpath("packages", "zone_development", "assured_runtime.py").is_file():
        raise ValueError("pinned private ADCP source is missing from the wrapper image")


class RuntimeBindingVerifier:
    reference = ecacc.VerifierRef("autobench.phase3d.runtime_binding", "1")
    evidence_kind = ecacc.EvidenceKind.STRUCTURE
    supported_obligations = (ecacc.ObligationKind.PRESERVATION,)

    def validate(self, definition):
        return () if definition.key == "exact-repository-binding" and not definition.parameters else ("Unsupported criterion",)

    def verify(self, criterion, context):
        if context.baseline is None or context.snapshot is None:
            return ecacc.VerifierObservation(sc.CriterionResult.NOT_RUN, self.evidence_kind, note="SOURCE_SNAPSHOTS_REQUIRED")
        checks = (
            ecacc.Check(
                "baseline-tree-bound",
                context.baseline.git_tree(context.candidate.binding.base_snapshot.tree.algorithm)
                == context.candidate.binding.base_snapshot.tree,
            ),
            ecacc.Check(
                "candidate-tree-bound",
                context.snapshot.git_tree(context.candidate.binding.snapshot.tree.algorithm)
                == context.candidate.binding.snapshot.tree,
            ),
        )
        return ecacc.VerifierObservation(
            sc.CriterionResult.PASS if all(check.passed for check in checks) else sc.CriterionResult.FAIL,
            self.evidence_kind,
            checks,
            "Local handoff integrity only; not task correctness",
        )


class NonEmptyCandidateVerifier:
    reference = ecacc.VerifierRef("autobench.phase3d.nonempty_candidate", "1")
    evidence_kind = ecacc.EvidenceKind.STRUCTURE
    supported_obligations = (ecacc.ObligationKind.ACHIEVEMENT,)

    def validate(self, definition):
        return () if definition.key == "nonempty-source-change" and not definition.parameters else ("Unsupported criterion",)

    def verify(self, criterion, context):
        changed = context.candidate.binding.snapshot.tree != context.candidate.binding.base_snapshot.tree
        return ecacc.VerifierObservation(
            sc.CriterionResult.PASS if changed else sc.CriterionResult.FAIL,
            self.evidence_kind,
            (ecacc.Check("candidate-tree-differs-from-baseline", changed),),
            "CANDIDATE_READY handoff requirement only; official SWE-bench owns task correctness",
        )


def _scope_payload(scope) -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy": scope.policy,
        "identity": scope.identity,
        "baseline_commit": scope.baseline_commit,
        "problem_sha256": scope.problem_sha256,
        "tokens": list(scope.tokens),
        "write_paths": list(scope.write_paths),
        "read_paths": list(scope.read_paths),
        "read_bytes": scope.read_bytes,
        "hidden_task_material_used": False,
    }


def _make_external_identity(task_id: str, pair_id: str):
    key = _safe_component(pair_id)
    repository = sc.RepositoryId(value="swebench-" + _safe_component(task_id))
    epoch = sc.ArchitectureEpoch(repository_id=repository, sequence=1)
    timestamp = sc.Timestamp(value=FIXED_TIMESTAMP)
    provenance = sc.Provenance(
        actor=sc.ActorRef(authority=sc.Authority.TASKOWNER, actor_id="phase3d-external-host"),
        recorded_at=timestamp,
    )
    task = sc.LogicalTaskRef(logical_task_id=sc.LogicalTaskId(value="phase3d-task-" + key))
    attempt_ref = sc.AttemptRef(
        task_node=sc.TaskNodeRef(logical_task=task, task_node_id=sc.TaskNodeId(value="phase3d-node-" + key)),
        attempt_id=sc.AttemptId(value="phase3d-attempt-" + key),
    )
    versions = sc.VersionVector(
        architecture_epoch=epoch,
        decision_package_revision=sc.DecisionPackageRevision(value=1),
        requirement_ledger_revision=sc.RequirementLedgerRevision(value=1),
        evaluation_contract_revision=sc.EvaluationContractRevision(value=1),
        implementation_plan_revision=sc.ImplementationPlanRevision(value=1),
        zone_manifest_version=sc.ZoneManifestVersion(value=1),
        permit_version=sc.PermitVersion(value=1),
        fence_seq=sc.FenceSeq(value=1),
    )
    attempt = sc.Attempt(
        ref=attempt_ref,
        root_budget_id=sc.RootBudgetId(value="phase3d-budget-" + key),
        record_revision=sc.AggregateRevision(value=1),
        attempt_number=1,
        status=sc.AttemptStatus.RUNNING,
        versions=versions,
        provenance=provenance,
    )
    return repository, attempt, versions, key


def _make_contract(attempt, versions, key):
    registry = ecacc.VerifierRegistry((RuntimeBindingVerifier(), NonEmptyCandidateVerifier()))
    intent = ecacc.TaskAcceptanceIntent(
        "phase3d-local-handoff-" + key,
        attempt.ref.task_node.logical_task.logical_task_id,
        versions.requirement_ledger_revision,
        (
            ecacc.Requirement(
                "candidate-handoff",
                "Produce a non-empty exact-bound local candidate; official SWE-bench remains the sole task-correctness authority",
                True,
                True,
                (
                    ecacc.Obligation(
                        ecacc.ObligationKind.PRESERVATION,
                        "Preserve exact repository binding across the local development handoff",
                        (
                            ecacc.CriterionDefinition(
                                "exact-repository-binding",
                                "Baseline and candidate source projections must match their complete Git tree identities",
                                RuntimeBindingVerifier.reference,
                                ecacc.EvidenceKind.STRUCTURE,
                            ),
                        ),
                    ),
                    ecacc.Obligation(
                        ecacc.ObligationKind.ACHIEVEMENT,
                        "Produce a non-empty source change for external evaluation",
                        (
                            ecacc.CriterionDefinition(
                                "nonempty-source-change",
                                "Candidate Git tree must differ from the exact baseline Git tree",
                                NonEmptyCandidateVerifier.reference,
                                ecacc.EvidenceKind.STRUCTURE,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    contract = ecacc.ContractCompiler(registry).compile(
        intent,
        ecacc.EvaluationScope(attempt.ref, versions),
        sc.ArtifactId(value="phase3d-contract-" + key),
        versions.evaluation_contract_revision,
    )
    if contract.blockers:
        raise ValueError(f"internal outcome-blind handoff contract failed to compile: {contract.blockers}")
    return registry, contract


@contextmanager
def authority_worktree(workspace: Path, root: Path, pair_id: str) -> Iterator[Path]:
    baseline = git(workspace, "rev-parse", "HEAD").strip()
    target = root / "authority"
    branch = "autobench-authority-" + _safe_component(pair_id)
    if target.exists():
        raise RuntimeError("authority worktree path unexpectedly already exists")
    git(workspace, "worktree", "add", "-b", branch, str(target), baseline)
    try:
        if git(target, "rev-parse", "HEAD").strip() != baseline:
            raise RuntimeError("authority worktree commit differs from Harbor baseline")
        if git(target, "status", "--porcelain", "--untracked-files=all").strip():
            raise RuntimeError("authority worktree is not clean")
        yield target
    finally:
        git(workspace, "worktree", "remove", "--force", str(target), ok=(0, 128))
        git(workspace, "branch", "-D", branch, ok=(0, 1))


class RoleSandboxFactory:
    def __init__(self, authority: Path, state_root: Path):
        self.authority = authority
        self.root = state_root / "role-worktrees"
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def __call__(self, command: DeepSeekRoleCommand) -> Iterator[Path]:
        payload = zone_wire.loads(command.input_json)
        if type(payload) is not dict or payload.get("input_schema") != "adcp.harness_bridge.ZoneRoleInput/2":
            raise RuntimeError("paid role command did not carry ZoneRoleInput/2")
        action = payload.get("action")
        source_ref = payload.get("source_ref")
        if source_ref != getattr(action, "source", None) or source_ref.commit is None:
            raise RuntimeError("paid role sandbox lacks an exact source commit binding")
        target = self.root / _safe_component(command.call_id)
        if target.exists():
            raise RuntimeError("role sandbox path unexpectedly already exists")
        git(self.authority, "worktree", "add", "--detach", str(target), source_ref.commit.value)
        try:
            if git(target, "rev-parse", "HEAD").strip() != source_ref.commit.value:
                raise RuntimeError("role sandbox commit differs from issued ActionRequest")
            if git(target, "rev-parse", "HEAD^{tree}").strip() != source_ref.tree.value:
                raise RuntimeError("role sandbox tree differs from issued ActionRequest")
            if git(target, "status", "--porcelain", "--untracked-files=all").strip():
                raise RuntimeError("fresh role sandbox is unexpectedly dirty")
            yield target
        finally:
            git(self.authority, "worktree", "remove", "--force", str(target), ok=(0, 128))


def export_ready_candidate(authority: Path, workspace: Path, baseline_commit: str, candidate_tree: str) -> None:
    if git(workspace, "rev-parse", "HEAD").strip() != baseline_commit:
        raise RuntimeError("Harbor workspace HEAD changed during ADCP execution")
    if git(workspace, "diff", "--quiet", "--no-ext-diff", "--", ok=(0, 1)).strip():
        # git diff --quiet emits no stdout; branch retained for defensive clarity.
        pass
    patch = git(authority, "diff", "--binary", baseline_commit + "..HEAD", "--")
    if not patch.strip():
        raise RuntimeError("CANDIDATE_READY authority worktree has no net source patch")
    encoded = patch.encode("utf-8")
    git(workspace, "apply", "--check", "--index", "-", input_bytes=encoded)
    git(workspace, "apply", "--index", "--whitespace=nowarn", "-", input_bytes=encoded)
    observed_tree = git(workspace, "write-tree").strip()
    if observed_tree != candidate_tree:
        raise RuntimeError(
            f"exported candidate tree mismatch: expected {candidate_tree}, observed {observed_tree}"
        )
    # Return Harbor workspace index to its exact baseline while retaining the
    # candidate as ordinary working-tree/untracked changes for independent patch export.
    git(workspace, "reset", "--mixed", "HEAD")


def _event_sequence(events) -> list[str]:
    mapping = {
        "LOCAL_ARCHITECT_STARTED": "ARCHITECT",
        "ARCHITECT_STARTED": "ARCHITECT",
        "CODER_STARTED": "CODER",
        "REVIEWER_STARTED": "REVIEWER",
        "VERIFIER_STARTED": "VERIFIER",
        "RESEARCHER_STARTED": "RESEARCHER",
        "HANDS_STARTED": "HANDS",
    }
    return [mapping[event["phase"]] for event in events if event.get("phase") in mapping]


def main() -> int:
    _validate_target_identity()
    if required_env("AUTOBENCH_PHASE3D_PAID_EXPERIMENT") != "1":
        raise ValueError("this runner is reserved for the paid Phase 3D execution path")

    instruction = Path(required_env("AUTOBENCH_ADCP_INSTRUCTION_PATH")).read_text(encoding="utf-8")
    result_path = Path(required_env("AUTOBENCH_ADCP_RESULT_PATH"))
    workspace = Path(required_env("AUTOBENCH_ADCP_WORKSPACE")).resolve(strict=True)
    pair_id = required_env("AUTOBENCH_PHASE3D_PAIR_ID")
    task_id = required_env("AUTOBENCH_PHASE3D_TASK_ID")
    int(required_env("AUTOBENCH_PHASE3D_REPEAT_INDEX"))
    int(required_env("AUTOBENCH_PHASE3D_SEED"))

    if git(workspace, "diff", "--quiet", "--no-ext-diff", "--", ok=(0, 1)) != "":
        raise RuntimeError("unexpected tracked diff output")
    baseline_commit = git(workspace, "rev-parse", "HEAD").strip()
    scope = project_task_scope(
        workspace,
        instruction,
        max_write_paths=SCOPE_MAX_WRITE_PATHS,
        max_read_paths=SCOPE_MAX_READ_PATHS,
        max_read_bytes=SCOPE_MAX_READ_BYTES,
    )
    if scope.baseline_commit != baseline_commit:
        raise RuntimeError("scope projection baseline changed before ADCP admission")

    state_root = Path("/tmp/autobench-phase3d-adcp") / _safe_component(pair_id)
    if state_root.exists():
        raise RuntimeError("fresh paid task environment already contains this ADCP state root")
    state_root.mkdir(parents=True)

    scope_output = Path(os.environ.get("AUTOBENCH_ADCP_SCOPE_RESULT_PATH", "/tmp/autobench-adcp-scope.json"))
    scope_output.write_text(json.dumps(_scope_payload(scope), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with authority_worktree(workspace, state_root, pair_id) as authority:
        repository, attempt, versions, key = _make_external_identity(task_id, pair_id)
        registry, contract = _make_contract(attempt, versions, key)
        development_journal = SessionJournal(state_root / "development.sqlite3")
        read_scope = ReadScope(paths=scope.read_paths)
        read_scope_artifact = development_journal.artifact(
            sc.serialize(read_scope), read_scope.SCHEMA, read_scope.VERSION
        )
        scope_bytes = json.dumps(_scope_payload(scope), sort_keys=True, separators=(",", ":")).encode("utf-8")
        scope_artifact = development_journal.artifact(
            scope_bytes, "autobench.phase3d.ScopeProjection", "1.0.0"
        )
        baseline = GitWorkspace(authority).source_ref(repository)
        request = DevelopmentWorkRequest(
            request_id="phase3d-request-" + key,
            session_id="phase3d-session-" + key,
            zone_id=sc.ZoneId(value="phase3d-zone-" + key),
            attempt=attempt,
            permit_id=sc.PermitId(value="phase3d-permit-" + key),
            baseline=baseline,
            evaluation_contract=contract.ref.artifact,
            write_scope=WriteScope(paths=scope.write_paths),
            limits=SessionLimits(
                max_role_calls=16,
                max_repairs=2,
                max_verifications=4,
                stall_limit=2,
                max_patch_bytes=262144,
                max_source_bytes=524288,
                max_replans=2,
                action_timeout_seconds=120,
            ),
            objective=instruction,
            workspace_id="phase3d-workspace-" + key,
            workspace_generation=1,
            requirements=(
                "Solve the public SWE-bench problem statement within the external WriteScope",
                "CANDIDATE_READY is a local handoff only; official SWE-bench v5 owns final correctness",
            ),
            context_refs=(contract.ref.artifact, read_scope_artifact, scope_artifact),
        )

        binding = DeepSeekHarnessBinding()
        protocol = DeepSeekHarnessProtocol(
            state_root=state_root / "dsh",
            base_url=required_env("DEEPSEEK_BASE_URL"),
            api_key=required_env("DEEPSEEK_API_KEY"),
            model=ADCP_MODEL_ROUTE,
            provider=ADCP_PROVIDER_ROUTE,
            profile="sdk",
            request_timeout_seconds=120,
            role_workspace=RoleSandboxFactory(authority, state_root),
        )
        exchange = ExchangeJournal(state_root / "exchange.sqlite3", DSH_BINDING_ID)
        gateway = HarnessGateway(protocol, binding, exchange)
        roles = RoleServices(
            HarnessLocalArchitect(
                gateway,
                RoleIdentity(role=Role.ARCHITECT, actor_id="phase3d-architect-" + key),
                context_binding=ContextBinding(),
            ),
            HarnessCoder(
                gateway,
                RoleIdentity(role=Role.CODER, actor_id="phase3d-coder-" + key),
                context_binding=ContextBinding(),
            ),
            HarnessReviewer(
                gateway,
                RoleIdentity(role=Role.REVIEWER, actor_id="phase3d-reviewer-" + key),
                context_binding=ContextBinding(),
            ),
            ECACCVerifier("phase3d-verifier-" + key, contract, registry),
        )
        runtime = ZoneDevelopmentRuntime(
            roles,
            development_journal,
            read_scope=read_scope,
            read_scope_artifact=read_scope_artifact,
        )
        outcome = runtime.develop(request, authority)
        if not isinstance(outcome, DevelopmentOutcome):
            raise RuntimeError(f"ADCP returned non-terminal waiting/control state: {type(outcome).__name__}")

        events = development_journal.events(request.session_id)
        sequence = _event_sequence(events)
        role_counts = {
            "architect": sequence.count("ARCHITECT"),
            "coder": sequence.count("CODER"),
            "reviewer": sequence.count("REVIEWER"),
            "verifier": sequence.count("VERIFIER"),
        }
        if protocol.model_calls != role_counts["architect"] + role_counts["coder"] + role_counts["reviewer"]:
            raise RuntimeError("DeepSeek Harness model-call count differs from model-backed ADCP role events")

        candidate_id = outcome.candidate.candidate_snapshot_id.value if outcome.candidate is not None else None
        if outcome.status is OutcomeStatus.CANDIDATE_READY:
            if outcome.candidate is None:
                raise RuntimeError("CANDIDATE_READY lacks a candidate")
            export_ready_candidate(
                authority,
                workspace,
                baseline_commit,
                outcome.candidate.binding.snapshot.tree.value,
            )

        receipt = {
            "schema": PHASE3D_ADCP_RECEIPT_SCHEMA,
            "target_runtime": {
                "repository": ADCP_REPOSITORY,
                "commit": ADCP_COMMIT,
                "runtime": ADCP_RUNTIME,
                "integration": ADCP_INTEGRATION,
            },
            "runtime_loaded": True,
            "role_ids": {
                "architect": roles.architect.identity.actor_id,
                "coder": roles.coder.identity.actor_id,
                "reviewer": roles.reviewer.identity.actor_id,
                "verifier": roles.verifier.identity.actor_id,
            },
            "role_call_counts": role_counts,
            "event_sequence": sequence,
            "outcome_status": outcome.status.value,
            "reason_code": outcome.reason_code,
            "candidate_ready": outcome.status is OutcomeStatus.CANDIDATE_READY,
            "task_completed": False,
            "model_route": ADCP_MODEL_ROUTE,
            "provider_route": ADCP_PROVIDER_ROUTE,
            "model_calls_via_budget_proxy": True,
            "upstream_provider_credential_present": bool(os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY")),
            "proxy_credential_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "model_called": protocol.model_calls > 0,
            "session_id": request.session_id,
            "request_id": request.request_id,
            "candidate_snapshot_id": candidate_id,
            "repair_count": outcome.session.repairs,
            "scope_projection_id": scope.identity,
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
