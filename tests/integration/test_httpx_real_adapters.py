"""Opt-in local end-to-end smoke through both real production APIs."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchmark_core.bootstrap import ProjectEnvironmentBuilder
from benchmark_core.cache import ActionCache
from benchmark_core.cas import FileSystemCAS
from benchmark_core.checkout import SharedGitCache, source_tree_digest
from benchmark_core.experiment import SystemUnderTest
from benchmark_core.isolation import IsolationCapabilities, IsolationPolicy
from benchmark_core.manifest import load_project, load_scenario, load_task
from benchmark_core.overlay import ScenarioCheckpointMaterializer
from benchmark_core.runner import ExperimentRunner
from benchmark_core.worktree import WorktreeManager
from corpus.adapters.httpx import HTTPX_DEVELOPMENT_BINDINGS as binding
from corpus.adapters.httpx_oracles import HttpxRefactoringOracleContextFactory
from suites.auto_refactoring import AutoRefactoringSuite, ProductionCliAdapter
from suites.auto_zoning import (
    AcceptableZoneSet, AutoZoningSuite, ProductionSemanticSubprocessAdapter, ResponsibilityLabel, ZoningOracleContext,
)


ROOT = Path(__file__).parents[2]
pytestmark = pytest.mark.skipif(os.getenv("AUTODEV_RUN_LOCAL_INTEGRATION") != "1", reason="opt-in local production packages")


def test_httpx_shared_scenario_runs_both_real_adapters(tmp_path: Path) -> None:
    refactoring_src = ROOT.parent / "autorefactoring" / "src"
    zoning_src = ROOT.parent / "autozoning-semantic-repair-v0.6.0" / "auto-zoning" / "src"
    if not refactoring_src.is_dir() or not zoning_src.is_dir():
        pytest.skip("local production source checkouts are unavailable")
    pythonpath = os.pathsep.join((str(refactoring_src), str(zoning_src), str(ROOT), str(ROOT / "packages/benchmark_core")))
    adapter_environment = {"PYTHONPATH": pythonpath}
    refactoring_digest = source_tree_digest(refactoring_src)
    zoning_digest = source_tree_digest(zoning_src)
    refactoring_commit = refactoring_digest.removeprefix("sha256:")[:40]
    zoning_commit = zoning_digest.removeprefix("sha256:")[:40]
    project = load_project(ROOT / "corpus/projects/httpx.pinned_001.json")
    task = load_task(ROOT / "tasks/httpx.add_transport_provider.v1.json")
    scenario = load_scenario(ROOT / "scenarios/real_world/httpx.add_transport_provider.shared.v1.json")
    snapshot = SharedGitCache(tmp_path / "git").ensure(
        project.source.repository, str(project.source.commit_sha),
        expected_source_tree_digest=str(project.source.source_tree_digest),
    )
    worktrees = WorktreeManager(tmp_path / "runs")
    baseline_worktree = worktrees.create(snapshot, tmp_path / "baseline-source")
    worktrees.verify_pristine(baseline_worktree, expected_source_tree_digest=str(project.source.source_tree_digest))
    baseline_cas = FileSystemCAS(tmp_path / "baseline-cas")
    baseline = ProjectEnvironmentBuilder(
        tmp_path / "environments", baseline_cas,
        cache=ActionCache(tmp_path / "baseline-actions.sqlite", baseline_cas),
    ).build_and_verify(project, baseline_worktree.path)
    assert baseline.admitted and baseline.environment is not None and baseline.python_executable is not None
    environment_digest = baseline.environment.digest
    materializer = ScenarioCheckpointMaterializer(
        overlay_handlers=binding.overlay_handlers, mutation_recipes=binding.mutation_recipes,
        mutation_parameters=binding.mutation_parameters,
        mechanics_identities=binding.mechanics_identities,
    )
    runner = ExperimentRunner(
        worktrees, isolation_policy=IsolationPolicy(authoritative=False),
        isolation_capabilities=IsolationCapabilities(True, True, True, True, True),
        cas=FileSystemCAS(tmp_path / "cas"),
    )
    zoning_invocation = task.project("auto_zoning", source_snapshot={
        "input_fingerprint": str(project.source.source_tree_digest), "scope_paths": ["httpx/_client.py"],
    })
    zoning_context = ZoningOracleContext(
        responsibilities=(
            ResponsibilityLabel("transport-provider-registry", ("transports",)),
            ResponsibilityLabel("client-integration", ("client_integration",)),
        ),
        acceptable_zone_sets=(AcceptableZoneSet(("transports", "client_integration")),), boundaries=(),
    )
    zoning = runner.run_suite(
        snapshot=snapshot, scenario=scenario, suite=AutoZoningSuite(), adapter=ProductionSemanticSubprocessAdapter((baseline.python_executable, "-m", "suites.auto_zoning.worker"), environment=adapter_environment),
        checkpoint_materializer=materializer, invocation=zoning_invocation, oracle_context=zoning_context,
        seed=819283, environment_digest=environment_digest,
        system=SystemUnderTest("auto-zoning", "0.6.0", zoning_commit, {"implementation_digest": zoning_digest, "executable_digest": baseline.environment.interpreter_executable_digest}),
        system_implementation_path=zoning_src, system_executable_path=baseline.python_executable,
    )
    refactoring = runner.run_suite(
        snapshot=snapshot, scenario=scenario, suite=AutoRefactoringSuite(), adapter=ProductionCliAdapter(
            (baseline.python_executable, "-m", "auto_refactoring.design_form"), environment=adapter_environment,
        ),
        checkpoint_materializer=materializer,
        invocation=task.project("auto_refactoring", candidate_snapshot={"affected_scope": "httpx"}),
        oracle_context=HttpxRefactoringOracleContextFactory(baseline.python_executable),
        seed=819283, environment_digest=environment_digest,
        system=SystemUnderTest("auto-refactoring", "0.10.0", refactoring_commit, {"implementation_digest": refactoring_digest, "executable_digest": baseline.environment.interpreter_executable_digest}),
        system_implementation_path=refactoring_src, system_executable_path=baseline.python_executable,
    )
    assert zoning.stage_results and refactoring.stage_results
    assert zoning.suite_id != refactoring.suite_id
    assert zoning.stage_results[0].observation.status.value == "PASS"
    assert zoning.stage_results[0].observation.attributes["raw_output"]["snapshot_binding_valid"] is True
    assert zoning.stage_results[0].observation.attributes["raw_output"]["files"]
    assert zoning.status.value == "FAIL"
    assert [item.status.value for item in zoning.oracle_results] == ["FAIL", "FAIL", "PASS"]
    assert set(zoning.suite_gate_outcomes) == {"no_unauthorized_owner_assignment"}
    assert set(zoning.global_gate_outcomes) == {"unauthorized_cross_zone_write", "lost_required_verification", "half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"}
    assert zoning.global_gate_outcomes["evidence_integrity_failure"] is False
    assert "evidence_integrity_failure" in {gate.value for gate in zoning.hard_gate_failures}
    assert abs(zoning.metrics["auto_zoning.proposal_mass"] + zoning.metrics["auto_zoning.partial_mass"] + zoning.metrics["auto_zoning.unknown_mass"] - 1.0) < 1e-9
    assert refactoring.stage_results[0].observation.status.value == "PASS"
    assert refactoring.stage_results[0].observation.attributes["process_status"] == 0
    assert refactoring.status.value == "FAIL"
    refactoring_oracles = {item.oracle_id: item for item in refactoring.oracle_results}
    probes = refactoring_oracles["design_opportunity.v3"].measurements["evidence"]["httpx_feature_probes"]
    assert refactoring_oracles["mutation_presence.independent.v1"].status.value == "PASS"
    assert refactoring_oracles["functional_regression.v2"].status.value == "FAIL"
    assert refactoring_oracles["differential_behavior.v1"].status.value == "FAIL", probes
    assert refactoring_oracles["public_api.v2"].status.value == "PASS", probes
    assert probes["counts"] == {"sync_created": 2, "sync_closed": 1, "async_created": 1, "async_closed": 1}
    assert probes["unknown_key_error"] is True and probes["injected_transport_preserved"] is True
    assert set(refactoring.global_gate_outcomes) == {"false_safe_certificate", "lost_required_verification", "half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"}
    assert "lost_required_verification" in {gate.value for gate in refactoring.hard_gate_failures}
    assert zoning.stage_results[0].input_fingerprint == str(project.source.source_tree_digest)
    assert refactoring.stage_results[0].input_fingerprint != zoning.stage_results[0].input_fingerprint
