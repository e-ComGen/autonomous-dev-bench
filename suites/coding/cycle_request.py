"""Benchmark-host issuance of an isolated Attempt; no production authority is created."""
from datetime import datetime, timezone
import shared_contracts as sc
from packages import ecacc
from packages.zone_development import DevelopmentWorkRequest, WriteScope, SessionLimits
from .public_verifier import PublicChecks


def compile_request(session, baseline, registry, settings, paths, objective):
    repository = baseline.repository_id
    task = sc.LogicalTaskRef(logical_task_id=sc.LogicalTaskId(value=session))
    attempt = sc.AttemptRef(task_node=sc.TaskNodeRef(logical_task=task, task_node_id=sc.TaskNodeId(value=session + "-node")),
                            attempt_id=sc.AttemptId(value=session + "-attempt"))
    versions = sc.VersionVector(architecture_epoch=sc.ArchitectureEpoch(repository_id=repository, sequence=1),
        decision_package_revision=sc.DecisionPackageRevision(value=1), requirement_ledger_revision=sc.RequirementLedgerRevision(value=1),
        evaluation_contract_revision=sc.EvaluationContractRevision(value=1), implementation_plan_revision=sc.ImplementationPlanRevision(value=1),
        zone_manifest_version=sc.ZoneManifestVersion(value=1), permit_version=sc.PermitVersion(value=1), fence_seq=sc.FenceSeq(value=1))
    provenance = sc.Provenance(actor=sc.ActorRef(authority=sc.Authority.TASKOWNER, actor_id="isolated-benchmark-host"),
        recorded_at=sc.Timestamp(value=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
    record = sc.Attempt(ref=attempt, root_budget_id=sc.RootBudgetId(value=session + "-budget"),
                        record_revision=sc.AggregateRevision(value=1), attempt_number=1,
                        status=sc.AttemptStatus.RUNNING, versions=versions, provenance=provenance)
    obligations = tuple(ecacc.Obligation(kind, description, (
        ecacc.CriterionDefinition(key, description, PublicChecks.reference, ecacc.EvidenceKind.BEHAVIOR),))
        for kind, key, description in ((ecacc.ObligationKind.ACHIEVEMENT, "achievement", "Pass the supplied public task checks"),
                                        (ecacc.ObligationKind.PRESERVATION, "preservation", "Preserve the supplied public regression checks")))
    intent = ecacc.TaskAcceptanceIntent(session + "-intent", task.logical_task_id, versions.requirement_ledger_revision,
        (ecacc.Requirement("public-task", objective, True, True, obligations),))
    contract = ecacc.ContractCompiler(registry).compile(intent, ecacc.EvaluationScope(attempt, versions),
        sc.ArtifactId(value=session + "-contract"), versions.evaluation_contract_revision)
    request = DevelopmentWorkRequest(request_id=session + "-request", session_id=session,
        zone_id=sc.ZoneId(value="benchmark-scope"), attempt=record, permit_id=sc.PermitId(value=session + "-permit"),
        baseline=baseline, evaluation_contract=contract.ref.artifact, write_scope=WriteScope(paths=tuple(paths)),
        limits=SessionLimits(max_role_calls=16, max_repairs=2, max_verifications=4, max_source_bytes=33554432,
                             max_patch_bytes=settings.max_patch_bytes, action_timeout_seconds=settings.arm_seconds),
        objective=objective, workspace_id=session + "-workspace", workspace_generation=1,
        requirements=(objective,), context_refs=(contract.ref.artifact,))
    return request, contract
