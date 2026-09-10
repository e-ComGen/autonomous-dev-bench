"""Generic production ADCP runner for one SWE-bench workspace.

This host glue intentionally knows only the public problem statement and the exact
baseline repository. It never reads gold.patch, test.patch, tests.json or official
outcomes. Internal ECACC certifies only a local handoff invariant: exact source
binding is preserved and the candidate is a non-empty source change. Official
SWE-bench v5 remains the sole task-correctness authority after the arm finishes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ADCP_ROOT = Path("/opt/autobench/adcp")
BENCH_ROOT = Path("/opt/autobench/bench")
sys.path[:0] = [str(ADCP_ROOT), str(ADCP_ROOT / "packages/shared_contracts/src"), str(BENCH_ROOT)]

import shared_contracts as sc
from packages import ecacc
from packages.harness_bridge.contracts import ContextBinding
from packages.harness_bridge.gateway import HarnessGateway
from packages.harness_bridge.journal import ExchangeJournal
from packages.harness_bridge.zone import HarnessCoder, HarnessLocalArchitect, HarnessReviewer
from packages.zone_development import (
    DevelopmentOutcome,
    DevelopmentWorkRequest,
    ECACCVerifier,
    GitWorkspace,
    OutcomeStatus,
    Role,
    RoleIdentity,
    RoleServices,
    SessionJournal,
    SessionLimits,
    WriteScope,
)
from packages.zone_development.assured_runtime import ZoneDevelopmentRuntime
from suites.coding.adcp_contract import (
    ADCP_COMMIT, ADCP_INTEGRATION, ADCP_MODEL_ROUTE, ADCP_PROVIDER_ROUTE,
    ADCP_RECEIPT_SCHEMA, ADCP_REPOSITORY, ADCP_RUNTIME,
)
from suites.coding.adcp_dsh_binding import DSH_BINDING_ID, DeepSeekHarnessBinding
from suites.coding.adcp_dsh_workspace_protocol import WorkspaceDeepSeekHarnessProtocol


class SourceBindingPreservation:
    reference = ecacc.VerifierRef("autobench.source_binding_preservation", "1")
    evidence_kind = ecacc.EvidenceKind.BEHAVIOR
    supported_obligations = (ecacc.ObligationKind.PRESERVATION,)

    def validate(self, definition):
        return () if definition.key == "exact-source-binding" and not definition.parameters else ("Unsupported criterion",)

    def verify(self, criterion, context):
        checks = (
            ecacc.Check("baseline_bound", context.baseline is not None and context.baseline.git_tree() == context.candidate.binding.base_snapshot.tree),
            ecacc.Check("candidate_bound", context.snapshot is not None and context.snapshot.git_tree() == context.candidate.binding.snapshot.tree),
        )
        return ecacc.VerifierObservation(
            sc.CriterionResult.PASS if all(item.passed for item in checks) else sc.CriterionResult.FAIL,
            self.evidence_kind, checks,
            "Local handoff integrity only; not task correctness",
        )


class NonEmptyChangeAchievement:
    reference = ecacc.VerifierRef("autobench.nonempty_source_change", "1")
    evidence_kind = ecacc.EvidenceKind.STRUCTURE
    supported_obligations = (ecacc.ObligationKind.ACHIEVEMENT,)

    def validate(self, definition):
        return () if definition.key == "nonempty-source-change" and not definition.parameters else ("Unsupported criterion",)

    def verify(self, criterion, context):
        changed = context.candidate.binding.snapshot.tree != context.candidate.binding.base_snapshot.tree
        checks = (ecacc.Check("tree_changed", changed),)
        return ecacc.VerifierObservation(
            sc.CriterionResult.PASS if changed else sc.CriterionResult.FAIL,
            self.evidence_kind, checks,
            "CANDIDATE_READY handoff criterion only; official SWE-bench grades correctness",
        )


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise RuntimeError(f"missing required environment variable {name}")
    return value


def git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    completed = subprocess.run(
        ["git", "-C", str(root), "-c", "core.autocrlf=false", *args],
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=30, env=env, check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr[-3000:])
    return completed.stdout.strip()


def main() -> int:
    workspace = Path(required("AUTOBENCH_ADCP_WORKSPACE")).resolve()
    instruction = Path(required("AUTOBENCH_ADCP_INSTRUCTION_PATH")).read_text(encoding="utf-8")
    output = Path(required("AUTOBENCH_ADCP_RESULT_PATH"))
    expected_commit = required("AUTOBENCH_ADCP_TARGET_COMMIT")
    if expected_commit != ADCP_COMMIT:
        raise RuntimeError("benchmark/runner ADCP commit identity mismatch")
    marker = ADCP_ROOT / "ADCP_COMMIT.txt"
    if marker.read_text(encoding="ascii").strip() != ADCP_COMMIT:
        raise RuntimeError("containerized ADCP source marker differs from benchmark pin")
    if required("AUTOBENCH_ADCP_TARGET_RUNTIME") != ADCP_RUNTIME or required("AUTOBENCH_ADCP_TARGET_INTEGRATION") != ADCP_INTEGRATION:
        raise RuntimeError("ADCP runtime/integration identity drift")
    if required("AUTOBENCH_ADCP_MODEL") != ADCP_MODEL_ROUTE or required("AUTOBENCH_ADCP_PROVIDER") != ADCP_PROVIDER_ROUTE:
        raise RuntimeError("ADCP model/provider identity drift")
    if os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"):
        raise RuntimeError("upstream provider credential leaked into ADCP runner")

    # External host action: attach the exact existing SWE-bench HEAD to an isolated
    # development branch without changing the baseline commit/tree.
    head = git(workspace, "rev-parse", "HEAD")
    git(workspace, "checkout", "-B", "autobench-adcp-development", head)
    worktree = GitWorkspace(workspace)
    baseline = worktree.source_ref(sc.RepositoryId(value="swebench-task-repository"))
    source = worktree.snapshot(max_bytes=33554432)
    writable = tuple(
        path for path, _ in source.files
        if path not in set(source.binary_paths) and dict(source.modes).get(path, "100644") != "120000"
    )
    if not writable:
        raise RuntimeError("SWE-bench baseline has no writable UTF-8 regular source files")

    identity_seed = hashlib.sha256((head + "\0" + instruction).encode("utf-8")).hexdigest()[:20]
    task = sc.LogicalTaskRef(logical_task_id=sc.LogicalTaskId(value="swebench-task-" + identity_seed))
    attempt_ref = sc.AttemptRef(
        task_node=sc.TaskNodeRef(logical_task=task, task_node_id=sc.TaskNodeId(value="swebench-node-" + identity_seed)),
        attempt_id=sc.AttemptId(value="swebench-attempt-" + identity_seed),
    )
    versions = sc.VersionVector(
        architecture_epoch=sc.ArchitectureEpoch(repository_id=baseline.repository_id, sequence=1),
        decision_package_revision=sc.DecisionPackageRevision(value=1),
        requirement_ledger_revision=sc.RequirementLedgerRevision(value=1),
        evaluation_contract_revision=sc.EvaluationContractRevision(value=1),
        implementation_plan_revision=sc.ImplementationPlanRevision(value=1),
        zone_manifest_version=sc.ZoneManifestVersion(value=1),
        permit_version=sc.PermitVersion(value=1),
        fence_seq=sc.FenceSeq(value=1),
    )
    provenance = sc.Provenance(
        actor=sc.ActorRef(authority=sc.Authority.TASKOWNER, actor_id="autobench-swebench-host"),
        recorded_at=sc.Timestamp(value="2026-09-10T00:00:00.000000Z"),
    )
    attempt = sc.Attempt(
        ref=attempt_ref, root_budget_id=sc.RootBudgetId(value="autobench-budget-" + identity_seed),
        record_revision=sc.AggregateRevision(value=1), attempt_number=1,
        status=sc.AttemptStatus.RUNNING, versions=versions, provenance=provenance,
    )

    registry = ecacc.VerifierRegistry((SourceBindingPreservation(), NonEmptyChangeAchievement()))
    intent = ecacc.TaskAcceptanceIntent(
        "autobench-public-handoff-" + identity_seed, task.logical_task_id,
        versions.requirement_ledger_revision,
        (ecacc.Requirement(
            "public-handoff", "Produce a reviewed source change for external official grading", True, True,
            (
                ecacc.Obligation(ecacc.ObligationKind.PRESERVATION, "Preserve exact source binding", (
                    ecacc.CriterionDefinition("exact-source-binding", "Baseline/candidate bytes stay exactly bound",
                                             SourceBindingPreservation.reference, ecacc.EvidenceKind.BEHAVIOR),
                )),
                ecacc.Obligation(ecacc.ObligationKind.ACHIEVEMENT, "Produce a non-empty source change", (
                    ecacc.CriterionDefinition("nonempty-source-change", "Candidate tree differs from baseline",
                                             NonEmptyChangeAchievement.reference, ecacc.EvidenceKind.STRUCTURE),
                )),
            ),
        )),
    )
    contract = ecacc.ContractCompiler(registry).compile(
        intent, ecacc.EvaluationScope(attempt_ref, versions),
        sc.ArtifactId(value="autobench-contract-" + identity_seed),
        versions.evaluation_contract_revision,
    )

    request = DevelopmentWorkRequest(
        request_id="autobench-request-" + identity_seed,
        session_id="autobench-session-" + identity_seed,
        zone_id=sc.ZoneId(value="swebench-zone"), attempt=attempt,
        permit_id=sc.PermitId(value="autobench-permit-" + identity_seed),
        baseline=baseline, evaluation_contract=contract.ref.artifact,
        write_scope=WriteScope(paths=writable),
        limits=SessionLimits(max_role_calls=16, max_repairs=2, max_verifications=4,
                            stall_limit=2, max_patch_bytes=262144,
                            max_source_bytes=33554432, max_replans=2,
                            action_timeout_seconds=180),
        objective=instruction,
        workspace_id="swebench-workspace-" + identity_seed,
        workspace_generation=1,
        requirements=("Use only public task statement and repository evidence", "Do not claim task completion"),
        context_refs=(contract.ref.artifact,),
    )

    state_root = Path("/tmp/autobench-adcp-state") / identity_seed
    binding = DeepSeekHarnessBinding()
    protocol = WorkspaceDeepSeekHarnessProtocol(
        state_root=state_root / "dsh",
        base_url=required("DEEPSEEK_BASE_URL"),
        api_key=required("DEEPSEEK_API_KEY"),
        model=ADCP_MODEL_ROUTE, provider=ADCP_PROVIDER_ROUTE,
        profile="sdk", request_timeout_seconds=180,
    )
    exchange = ExchangeJournal(state_root / "exchange.sqlite3", DSH_BINDING_ID)
    gateway = HarnessGateway(protocol, binding, exchange)
    fresh = ContextBinding()
    roles = RoleServices(
        HarnessLocalArchitect(gateway, RoleIdentity(role=Role.ARCHITECT, actor_id="dsh-local-architect"), context_binding=fresh),
        HarnessCoder(gateway, RoleIdentity(role=Role.CODER, actor_id="dsh-coder"), context_binding=fresh),
        HarnessReviewer(gateway, RoleIdentity(role=Role.REVIEWER, actor_id="dsh-reviewer"), context_binding=fresh),
        ECACCVerifier("deterministic-public-handoff-verifier", contract, registry),
    )
    journal = SessionJournal(state_root / "development.sqlite3")
    outcome = ZoneDevelopmentRuntime(roles, journal).develop(request, workspace)
    if not isinstance(outcome, DevelopmentOutcome):
        raise RuntimeError(f"ADCP runtime did not reach a terminal DevelopmentOutcome: {type(outcome).__name__}")

    events = journal.events(request.session_id)
    phase_map = {
        "LOCAL_ARCHITECT_STARTED": "ARCHITECT", "CODER_STARTED": "CODER",
        "REVIEWER_STARTED": "REVIEWER", "VERIFIER_STARTED": "VERIFIER",
    }
    sequence = [phase_map[event["phase"]] for event in events if event.get("phase") in phase_map]
    counts = {name: sequence.count(name.upper() if name != "architect" else "ARCHITECT") for name in ("architect", "coder", "reviewer", "verifier")}
    candidate_id = outcome.candidate.candidate_snapshot_id.value if outcome.candidate else "none"
    receipt = {
        "schema": ADCP_RECEIPT_SCHEMA,
        "target_runtime": {"repository": ADCP_REPOSITORY, "commit": ADCP_COMMIT, "runtime": ADCP_RUNTIME, "integration": ADCP_INTEGRATION},
        "runtime_loaded": True,
        "fake_runtime": False,
        "role_ids": {"architect": roles.architect.identity.actor_id, "coder": roles.coder.identity.actor_id,
                     "reviewer": roles.reviewer.identity.actor_id, "verifier": roles.verifier.identity.actor_id},
        "role_call_counts": counts,
        "event_sequence": sequence,
        "outcome_status": outcome.status.value,
        "candidate_ready": outcome.status is OutcomeStatus.CANDIDATE_READY,
        "task_completed": False,
        "model_route": ADCP_MODEL_ROUTE,
        "provider_route": ADCP_PROVIDER_ROUTE,
        "model_calls_via_budget_proxy": os.environ.get("AUTOBENCH_MODEL_PROXY_MODE") == "1",
        "upstream_provider_credential_present": bool(os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY")),
        "proxy_credential_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "model_called": protocol.model_calls > 0,
        "session_id": request.session_id,
        "request_id": request.request_id,
        "candidate_snapshot_id": candidate_id,
        "repair_count": outcome.session.repairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
