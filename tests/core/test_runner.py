from pathlib import Path
import hashlib
import json
import subprocess
import sys
import pytest

from benchmark_core.cache import ActionCache
from benchmark_core.cas import FileSystemCAS
from benchmark_core.checkout import SharedGitCache
from benchmark_core.execution import CommandSpec, ExecutionResult, ProcessRunner
from benchmark_core.environment import baseline_action_key, BaselineHealth
from benchmark_core.evidence import EvidenceBundleWriter
from benchmark_core.experiment import EvaluationLevel, ExecutionComposition, ExperimentSpec, SuitePlan, SystemUnderTest
from benchmark_core.identity import Sha256Digest
from benchmark_core.isolation import IsolationCapabilities, IsolationPolicy, SandboxAttestation, SandboxTrustStore, sandbox_provider_artifact_digest
from benchmark_core.overlay import MaterializationRecord
from benchmark_core.project import (BaselineSpec, BootstrapSpec, ClassificationSpec, CommandSpec as ProjectCommandSpec,
    CorpusSpec, LegalSpec, PlatformSpec, ProjectSource, ProjectSpec, SecuritySpec)
from benchmark_core.result import OracleResult, RunStatus, SuiteResult, SystemObservation
from benchmark_core.scenario import CheckpointSpec, ScenarioExecution, ScenarioSpec
from benchmark_core.task import ArchitectureConstraints, ExpectedScope, FunctionalOracleRef, TaskSpec
from benchmark_core.runner import ExperimentRunner
from benchmark_core.worktree import WorktreeManager


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def test_runner_owns_workspace_and_keeps_oracle_context_from_adapter(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "bench@example.invalid")
    _git(source, "config", "user.name", "Benchmark")
    (source / "value.txt").write_text("baseline", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "baseline")
    commit = _git(source, "rev-parse", "HEAD")
    snapshot = SharedGitCache(tmp_path / "git-cache").ensure(str(source), commit)

    private_context = object()
    seen: dict[str, object] = {}

    class Materializer:
        def apply(self, workspace: Path, scenario: object, checkpoint_id: str) -> None:
            seen["checkpoint"] = checkpoint_id

    class Adapter:
        adapter_id = "fake.production.v1"
        adapter_version = "1"
        execution_boundary = "subprocess"

        def invoke(self, invocation: object, run_context: object) -> SystemObservation:
            seen["invocation"] = invocation
            seen["workspace"] = getattr(run_context, "workspace")
            assert private_context is not invocation
            return SystemObservation("PASS", attributes={"raw_output": "captured"})

    class Suite:
        def plan(self, scenario: object) -> SuitePlan:
            return SuitePlan("fake-suite", "1", "task-ready", "fake.production.v1", (), ("raw_output",), ())

        def evaluate(self, scenario: object, observation: SystemObservation, oracle_context: object) -> SuiteResult:
            assert oracle_context is private_context
            return SuiteResult("fake-suite", "1", RunStatus.PASS, ())

    runs = tmp_path / "runs"
    result = ExperimentRunner(
        WorktreeManager(runs),
        isolation_policy=IsolationPolicy(authoritative=False),
        isolation_capabilities=IsolationCapabilities(True, True, True, True, True),
    ).run_suite(
        snapshot=snapshot,
        scenario={"id": "answer-free"},
        suite=Suite(),
        adapter=Adapter(),
        checkpoint_materializer=Materializer(),
        invocation={"user_request": "public projection only"},
        oracle_context=private_context,
        seed=7,
    )
    assert result.passed
    assert seen["checkpoint"] == "task-ready"
    assert result.stage_results[0].input_fingerprint
    assert result.stage_results[0].completed_at
    assert list(runs.glob("worktree-*")) == []


def test_caller_capability_booleans_cannot_claim_authoritative_isolation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sandbox trust store"):
        ExperimentRunner(
            WorktreeManager(tmp_path / "runs-no-provider"), cas=FileSystemCAS(tmp_path / "cas-no-provider"),
            isolation_capabilities=IsolationCapabilities(True, True, True, True, True),
        )


def test_authoritative_runner_owns_command_and_captures_cas_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source-command"
    source.mkdir(); _git(source, "init"); _git(source, "config", "user.email", "bench@example.invalid"); _git(source, "config", "user.name", "Benchmark")
    (source / "value.txt").write_text("baseline", encoding="utf-8")
    _git(source, "add", "."); _git(source, "commit", "-m", "baseline")
    snapshot = SharedGitCache(tmp_path / "command-cache").ensure(str(source), _git(source, "rev-parse", "HEAD"))

    dependency_digest = "sha256:" + hashlib.sha256((source / "value.txt").read_bytes()).hexdigest()
    project = ProjectSpec(
        "source-command", "1", ProjectSource(str(source), snapshot.commit, snapshot.source_tree_digest),
        LegalSpec("MIT", dependency_digest, "value.txt"), PlatformSpec(("windows",), ("3.11",)),
        BootstrapSpec("python-standard", (dependency_digest,), ("value.txt",), ()),
        BaselineSpec((ProjectCommandSpec("smoke", ("python", "-c", "pass"), 30),)),
        ClassificationSpec("tiny", ("testing",)), SecuritySpec("package_indices_only", "none"), CorpusSpec("test", "development"),
    )
    task = TaskSpec(
        "runner-task", "1", project.project_id, "task-ready", "public request",
        ExpectedScope(("testing",), ("testing",)), (), FunctionalOracleRef("functional", "1"),
        ArchitectureConstraints(("existing",), ()),
    )
    scenario = ScenarioSpec(
        "runner-command", "1", "source-command", "runner-task", (CheckpointSpec("task-ready"),), "task-ready",
        execution=ScenarioExecution("fresh_process", 30, {"network": "none"}), suite_ids=("fake-suite",),
    )

    class Materializer:
        def apply(self, workspace: Path, scenario: object, checkpoint_id: str) -> object:
            return MaterializationRecord(checkpoint_id, (), (), {})

    calls = {"prepare": 0, "evaluate": 0}

    class Adapter:
        adapter_id = "fake.command.v1"; adapter_version = "1"; read_only = True
        def validate_system_binding(self, system: object, implementation_path: Path, executable_path: Path) -> bool:
            return True
        def prepare_command(self, invocation: object, run_context: object) -> CommandSpec:
            calls["prepare"] += 1
            return CommandSpec((sys.executable, "-c", "import json; print(json.dumps({'raw_output':'captured'}))"), cwd=str(getattr(run_context, "workspace")))
        def parse_execution(self, execution: ExecutionResult) -> SystemObservation:
            return SystemObservation("PASS", attributes=json.loads(execution.stdout))

    suite_plan = SuitePlan("fake-suite", "1", "task-ready", "fake.command.v1", ("fake-oracle",), ("raw_output",), (), adapter_version="1", global_hard_gate_ids=("half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"))
    class Suite:
        def plan(self, scenario: object) -> SuitePlan:
            return suite_plan
        def evaluate(self, scenario: object, observation: SystemObservation, oracle_context: object) -> SuiteResult:
            calls["evaluate"] += 1
            return SuiteResult("fake-suite", "1", "PASS", (OracleResult("fake-oracle", "1", "PASS"),), suite_gate_outcomes={}, global_gate_outcomes={})

    cas = FileSystemCAS(tmp_path / "cas")
    capabilities = IsolationCapabilities(True, True, True, True, True)
    provider_digest = ""
    class TestSandboxProvider:
        def attest(self) -> SandboxAttestation:
            return SandboxAttestation("test-sandbox", "1", provider_digest, capabilities)
        def run(self, command: CommandSpec, *, policy: IsolationPolicy) -> ExecutionResult:
            return ProcessRunner(capabilities=capabilities).run(command, policy=IsolationPolicy(authoritative=False))
    provider = TestSandboxProvider()
    provider_digest = sandbox_provider_artifact_digest(provider)
    runner = ExperimentRunner(
        WorktreeManager(tmp_path / "command-runs"), cas=cas,
        isolation_policy=IsolationPolicy(trusted_provider_id="test-sandbox", trusted_provider_digest=provider_digest),
        action_cache=ActionCache(tmp_path / "actions.sqlite", cas), sandbox_provider=provider,
        sandbox_trust_store=SandboxTrustStore({"test-sandbox": provider}),
    )
    digest = "sha256:" + "a" * 64
    baseline_command = CommandSpec((str(Path(sys.executable).resolve()), "-c", "pass"), 30, cwd=str(source))
    baseline_result = ExecutionResult(baseline_command.argv, 0, "", "", False, 0.0)
    baseline_payload = json.dumps({"argv": list(baseline_result.argv), "returncode": 0, "stderr": "", "stdout": "", "timed_out": False}, separators=(",", ":"), sort_keys=True)
    baseline_spec = {"argv": baseline_command.argv, "timeout_seconds": 30, "cwd": str(source), "environment": {}, "stdin": None}
    attestation_digest = str(Sha256Digest.of(provider.attest()))
    baseline_key = baseline_action_key(digest, baseline_command, project_digest=str(project.content_digest), baseline_revision="1", executor_version="3", test_policy_version="1", authoritative=True, sandbox_attestation_digest=attestation_digest)
    baseline = BaselineHealth(
        str(project.content_digest), digest, str(Sha256Digest.of(baseline_spec)), "3", "1", "1", "2026-01-01T00:00:00+00:00", True, RunStatus.PASS,
        baseline_result, cas.put_text(baseline_payload), baseline_key, True, attestation_digest, baseline_spec,
    )
    executable_digest = "sha256:" + hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    system = SystemUnderTest("fake-system", "1", "c" * 40, {
        "implementation_digest": str(snapshot.source_tree_digest), "executable_digest": executable_digest,
    })
    experiment = ExperimentSpec(
        "runner-experiment", "1", project.identity, scenario.identity, task.identity, system, (suite_plan,), digest,
        EvaluationLevel.L1_DETERMINISTIC_SUBSYSTEM, ExecutionComposition.SUBSYSTEM, attempts=1, seeds=(1,),
        oracle_bindings={"fake-suite": {"labels_digest": str(Sha256Digest.of({})), "oracle_implementation_digest": str(Sha256Digest.of({"implementation": "builtins.dict"}))}},
    )
    arguments = dict(
        snapshot=snapshot, scenario=scenario, suite=Suite(), adapter=Adapter(),
        checkpoint_materializer=Materializer(), invocation={"user_request": "public"},
        oracle_context={}, seed=1, environment_digest=digest,
        system=system, baseline_health=(baseline,), project=project, task=task,
        system_implementation_path=source, system_executable_path=sys.executable, experiment=experiment,
        evidence=EvidenceBundleWriter(tmp_path / "evidence", cas), evidence_receipt_path=tmp_path / "receipts/first.sha256",
    )
    result = runner.run_suite(**arguments)
    assert result.global_gate_outcomes == {
        "half_applied_transaction": True, "accepted_stale_candidate": True, "evidence_integrity_failure": True,
    }
    cached_arguments = dict(arguments)
    cached_arguments["evidence"] = EvidenceBundleWriter(tmp_path / "evidence-cached", cas)
    cached_arguments["evidence_receipt_path"] = tmp_path / "receipts/cached.sha256"
    assert runner.run_suite(**cached_arguments).passed
    assert calls == {"prepare": 1, "evaluate": 1}
    fresh_arguments = dict(arguments)
    fresh_arguments["evidence"] = EvidenceBundleWriter(tmp_path / "evidence-fresh", cas)
    fresh_arguments["evidence_receipt_path"] = tmp_path / "receipts/fresh.sha256"
    assert runner.run_suite(**fresh_arguments, forced_fresh=True).passed
    assert calls == {"prepare": 2, "evaluate": 2}
    assert result.passed
    assert len(result.stage_results[0].evidence_refs) == 2
    for ref in result.stage_results[0].evidence_refs: cas.verify(ref)
