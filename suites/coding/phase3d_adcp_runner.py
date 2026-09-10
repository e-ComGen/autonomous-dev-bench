"""Production operator runner for one paid ADCP SWE-bench arm.

This file is copied into the task image as ``/opt/autobench/run_adcp.py``. It is
an external single-Zone host around the pinned private ZoneDevelopmentRuntime.
It uses only the public task instruction + baseline repository for scope and for
a deliberately weak internal handoff contract. Official SWE-bench remains the
only task-correctness authority after the runner returns.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from suites.coding.adcp_contract import (
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_MODEL_ROUTE,
    ADCP_PAID_RECEIPT_SCHEMA,
    ADCP_PROVIDER_ROUTE,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
)
from suites.coding.adcp_dsh_binding import DeepSeekHarnessBinding, DeepSeekHarnessProtocol
from suites.coding.phase3d_scope import SCOPE_POLICY, select_write_scope


INTERNAL_EVALUATION_POLICY = "phase3d-public-handoff-canonical-binding-v2"
SOURCE_BYTES = 512 * 1024
PATCH_BYTES = 262144
MAX_ROLE_CALLS = 16
MAX_REPAIRS = 2
MAX_VERIFICATIONS = 4
MAX_REPLANS = 2
ACTION_TIMEOUT_SECONDS = 120


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    completed = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env=env,
        check=False,
    )
    if check and completed.returncode:
        raise RuntimeError(completed.stderr[-2000:])
    return completed


def configure_private_adcp() -> Path:
    root = Path(os.environ.get("AUTOBENCH_ADCP_SOURCE_ROOT", "/opt/adcp")).resolve()
    pin_file = root / "ADCP_SOURCE_COMMIT"
    if not pin_file.is_file() or pin_file.read_text(encoding="ascii").strip() != ADCP_COMMIT:
        raise ValueError("task image does not contain the exact pinned ADCP source archive")
    shared = root / "packages" / "shared_contracts" / "src"
    if not (shared / "shared_contracts" / "__init__.py").is_file():
        raise ValueError("pinned ADCP shared_contracts source is missing")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(shared))
    return root


def require_target_environment() -> None:
    expected = {
        "AUTOBENCH_ADCP_TARGET_REPOSITORY": ADCP_REPOSITORY,
        "AUTOBENCH_ADCP_TARGET_COMMIT": ADCP_COMMIT,
        "AUTOBENCH_ADCP_TARGET_RUNTIME": ADCP_RUNTIME,
        "AUTOBENCH_ADCP_TARGET_INTEGRATION": ADCP_INTEGRATION,
        "AUTOBENCH_ADCP_MODEL": ADCP_MODEL_ROUTE,
        "AUTOBENCH_ADCP_PROVIDER": ADCP_PROVIDER_ROUTE,
        "AUTOBENCH_MODEL_PROXY_MODE": "1",
    }
    mismatches = [name for name, value in expected.items() if os.environ.get(name) != value]
    if mismatches:
        raise ValueError("ADCP paid runner identity mismatch: " + ",".join(mismatches))
    if os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"):
        raise ValueError("paid ADCP runner must not possess the upstream provider credential")


def prepare_worktree(workspace: Path) -> str:
    if Path(run_git(workspace, "rev-parse", "--show-toplevel").stdout.strip()).resolve() != workspace:
        raise ValueError("ADCP workspace must be the root of the official task repository")
    if run_git(workspace, "status", "--porcelain", "--untracked-files=all").stdout:
        raise ValueError("ADCP paid workspace must start clean")
    baseline = run_git(workspace, "rev-parse", "HEAD").stdout.strip().lower()
    if len(baseline) != 40:
        raise ValueError("ADCP paid workspace requires a SHA-1 baseline")
    symbolic = run_git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = symbolic.stdout.strip() if symbolic.returncode == 0 else ""
    if not branch or branch in {"main", "master"}:
        branch_name = "autobench-zone-" + hashlib.sha256(baseline.encode("ascii")).hexdigest()[:16]
        run_git(workspace, "switch", "-c", branch_name)
    return baseline


def _canonical_ids(instance_hint: str, baseline: str) -> dict[str, str]:
    prefix = hashlib.sha256((instance_hint + "\0" + baseline).encode("utf-8")).hexdigest()[:24]
    return {
        "repository": "repo-" + prefix,
        "task": "task-" + prefix,
        "node": "node-" + prefix,
        "attempt": "attempt-" + prefix,
        "budget": "budget-" + prefix,
        "permit": "permit-" + prefix,
        "request": "request-" + prefix,
        "session": "session-" + prefix,
        "zone": "zone-" + prefix,
        "workspace": "workspace-" + prefix,
        "contract": "contract-" + prefix,
    }


def main() -> int:
    require_target_environment()
    configure_private_adcp()

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
        OutcomeStatus,
        Role,
        RoleIdentity,
        RoleServices,
        SessionJournal,
        SessionLimits,
        WriteScope,
        ZoneDevelopmentRuntime,
    )
    from packages.zone_development.workspace import GitWorkspace

    class PublicHandoffVerifier:
        reference = ecacc.VerifierRef("autobench.public_handoff", "2")
        evidence_kind = ecacc.EvidenceKind.STRUCTURE
        supported_obligations = (ecacc.ObligationKind.PRESERVATION, ecacc.ObligationKind.ACHIEVEMENT)

        def __init__(self, expected_baseline):
            self.expected_baseline = expected_baseline

        def validate(self, definition):
            if definition.key not in {"exact-source-binding", "nonempty-candidate-change"} or definition.parameters:
                return ("Unsupported public handoff criterion",)
            return ()

        def verify(self, criterion, context):
            candidate = context.candidate
            binding = candidate.binding
            if criterion.definition.key == "exact-source-binding":
                checks = (
                    ecacc.Check("exact-base-source-ref", binding.base_snapshot == self.expected_baseline),
                    ecacc.Check(
                        "same-repository",
                        binding.snapshot.repository_id == self.expected_baseline.repository_id,
                    ),
                    ecacc.Check(
                        "same-git-object-algorithm",
                        binding.snapshot.tree.algorithm == self.expected_baseline.tree.algorithm,
                    ),
                    ecacc.Check("candidate-commit-bound", binding.snapshot.commit is not None),
                )
            else:
                checks = (
                    ecacc.Check(
                        "nonempty-tree-delta",
                        binding.snapshot.tree != binding.base_snapshot.tree,
                    ),
                )
            result = sc.CriterionResult.PASS if all(check.passed for check in checks) else sc.CriterionResult.FAIL
            return ecacc.VerifierObservation(
                result,
                self.evidence_kind,
                checks,
                "Canonical Git binding handoff only; official SWE-bench is task correctness authority",
            )

    instruction_path = Path(required_env("AUTOBENCH_ADCP_INSTRUCTION_PATH"))
    result_path = Path(required_env("AUTOBENCH_ADCP_RESULT_PATH"))
    workspace = Path(os.environ.get("AUTOBENCH_ADCP_WORKSPACE", "/workspace")).resolve()
    instruction = instruction_path.read_text(encoding="utf-8")
    baseline_commit = prepare_worktree(workspace)
    scope = select_write_scope(str(workspace), instruction)
    if scope.policy != SCOPE_POLICY or scope.baseline_commit != baseline_commit:
        raise ValueError("static Zone scope is not bound to the exact task baseline")

    instance_hint = os.environ.get("AUTOBENCH_INSTANCE_ID", instruction_path.stem)
    ids = _canonical_ids(instance_hint, baseline_commit)
    repository = sc.RepositoryId(value=ids["repository"])
    epoch = sc.ArchitectureEpoch(repository_id=repository, sequence=1)
    timestamp = sc.Timestamp(value="2026-09-10T00:00:00.000000Z")
    provenance = sc.Provenance(
        actor=sc.ActorRef(authority=sc.Authority.TASKOWNER, actor_id="autobench-external-zone-host"),
        recorded_at=timestamp,
    )
    logical_ref = sc.LogicalTaskRef(logical_task_id=sc.LogicalTaskId(value=ids["task"]))
    attempt_ref = sc.AttemptRef(
        task_node=sc.TaskNodeRef(logical_task=logical_ref, task_node_id=sc.TaskNodeId(value=ids["node"])),
        attempt_id=sc.AttemptId(value=ids["attempt"]),
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
        root_budget_id=sc.RootBudgetId(value=ids["budget"]),
        record_revision=sc.AggregateRevision(value=1),
        attempt_number=1,
        status=sc.AttemptStatus.RUNNING,
        versions=versions,
        provenance=provenance,
    )

    git_workspace = GitWorkspace(workspace)
    baseline_ref = git_workspace.source_ref(repository)
    verifier = PublicHandoffVerifier(baseline_ref)
    registry = ecacc.VerifierRegistry((verifier,))
    intent = ecacc.TaskAcceptanceIntent(
        "autobench-public-handoff",
        logical_ref.logical_task_id,
        versions.requirement_ledger_revision,
        (
            ecacc.Requirement(
                "public-task-candidate",
                "Produce a scoped candidate for external official evaluation",
                True,
                True,
                (
                    ecacc.Obligation(
                        ecacc.ObligationKind.PRESERVATION,
                        "Retain exact baseline/candidate source binding",
                        (
                            ecacc.CriterionDefinition(
                                "exact-source-binding",
                                "Canonical exact Git source identities remain bound",
                                verifier.reference,
                                ecacc.EvidenceKind.STRUCTURE,
                            ),
                        ),
                    ),
                    ecacc.Obligation(
                        ecacc.ObligationKind.ACHIEVEMENT,
                        "Produce a non-empty candidate tree change",
                        (
                            ecacc.CriterionDefinition(
                                "nonempty-candidate-change",
                                "Candidate Git tree differs from baseline",
                                verifier.reference,
                                ecacc.EvidenceKind.STRUCTURE,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    evaluation_scope = ecacc.EvaluationScope(attempt_ref, versions)
    contract = ecacc.ContractCompiler(registry).compile(
        intent,
        evaluation_scope,
        sc.ArtifactId(value=ids["contract"]),
        versions.evaluation_contract_revision,
    )

    request = DevelopmentWorkRequest(
        request_id=ids["request"],
        session_id=ids["session"],
        zone_id=sc.ZoneId(value=ids["zone"]),
        attempt=attempt,
        permit_id=sc.PermitId(value=ids["permit"]),
        baseline=baseline_ref,
        evaluation_contract=contract.ref.artifact,
        write_scope=WriteScope(paths=scope.paths),
        limits=SessionLimits(
            max_role_calls=MAX_ROLE_CALLS,
            max_repairs=MAX_REPAIRS,
            max_verifications=MAX_VERIFICATIONS,
            stall_limit=2,
            max_patch_bytes=PATCH_BYTES,
            max_source_bytes=SOURCE_BYTES,
            max_replans=MAX_REPLANS,
            action_timeout_seconds=ACTION_TIMEOUT_SECONDS,
        ),
        objective=instruction,
        workspace_id=ids["workspace"],
        workspace_generation=1,
        requirements=("Public task instruction is the only task-semantic input",),
        context_refs=(contract.ref.artifact,),
    )

    state_root = Path("/tmp/autobench-adcp-state") / ids["session"]
    state_root.mkdir(parents=True, exist_ok=True)
    binding = DeepSeekHarnessBinding()
    protocol = DeepSeekHarnessProtocol(
        state_root=state_root / "dsh",
        base_url=required_env("DEEPSEEK_BASE_URL"),
        api_key=required_env("DEEPSEEK_API_KEY"),
        model=ADCP_MODEL_ROUTE,
        provider=ADCP_PROVIDER_ROUTE,
        request_timeout_seconds=120,
    )
    gateway = HarnessGateway(
        protocol,
        binding,
        ExchangeJournal(state_root / "exchange.sqlite3", binding.binding_id),
    )
    fresh = ContextBinding()
    roles = RoleServices(
        HarnessLocalArchitect(gateway, RoleIdentity(role=Role.ARCHITECT, actor_id="paid-local-architect"), context_binding=fresh),
        HarnessCoder(gateway, RoleIdentity(role=Role.CODER, actor_id="paid-coder"), context_binding=fresh),
        HarnessReviewer(gateway, RoleIdentity(role=Role.REVIEWER, actor_id="paid-reviewer"), context_binding=fresh),
        ECACCVerifier("paid-public-handoff-verifier", contract, registry),
    )
    journal = SessionJournal(state_root / "development.sqlite3")
    runtime = ZoneDevelopmentRuntime(roles, journal)
    outcome = runtime.develop(request, workspace)
    if not isinstance(outcome, DevelopmentOutcome):
        raise RuntimeError(f"ADCP paid run did not reach a canonical terminal outcome: {type(outcome).__name__}")

    events = journal.events(request.session_id)
    phase_to_role = {
        "LOCAL_ARCHITECT_STARTED": "ARCHITECT",
        "CODER_STARTED": "CODER",
        "REVIEWER_STARTED": "REVIEWER",
        "VERIFIER_STARTED": "VERIFIER",
    }
    event_sequence = [phase_to_role[event["phase"]] for event in events if event.get("phase") in phase_to_role]
    counts = {name: event_sequence.count(name.upper()) for name in ("architect", "coder", "reviewer", "verifier")}
    candidate_id = outcome.candidate.candidate_snapshot_id.value if outcome.candidate is not None else None
    receipt = {
        "schema": ADCP_PAID_RECEIPT_SCHEMA,
        "target_runtime": {"repository": ADCP_REPOSITORY, "commit": ADCP_COMMIT, "runtime": ADCP_RUNTIME, "integration": ADCP_INTEGRATION},
        "runtime_loaded": True,
        "fake_runtime": False,
        "role_ids": {"architect": roles.architect.identity.actor_id, "coder": roles.coder.identity.actor_id, "reviewer": roles.reviewer.identity.actor_id, "verifier": roles.verifier.identity.actor_id},
        "role_call_counts": counts,
        "event_sequence": event_sequence,
        "outcome_status": outcome.status.value,
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
        "scope_policy": scope.policy,
        "scope_digest": scope.digest,
        "write_scope_paths": list(scope.paths),
        "internal_evaluation_policy": INTERNAL_EVALUATION_POLICY,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
