"""Platform-owned suite orchestration.

Suites choose a checkpoint and interpret observations.  This runner alone owns
worktree creation, isolation validation, invocation capture and stage evidence.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import inspect
import json
import tempfile
from typing import Any, Protocol

from .cache import ActionCache, observation_action_key, oracle_action_key
from .cas import FileSystemCAS
from .checkout import RepositorySnapshot, source_tree_digest
from .environment import baseline_action_key, BaselineHealth
from .evidence import EvidenceBundleVerifier, EvidenceBundleWriter
from .execution import CommandSpec, ExecutionResult, ProcessRunner, SandboxProvider
from .experiment import ExperimentSpec, SuitePlan, SystemUnderTest
from .identity import Sha256Digest, canonical_json
from .isolation import IsolationCapabilities, IsolationPolicy, SandboxTrustStore, local_process_capabilities, validate_isolation
from .overlay import MaterializationRecord
from .project import ProjectSpec
from .scenario import ScenarioSpec
from .task import TaskSpec
from .result import HardGate, OracleResult, RunStatus, StageResult, SuiteResult, SystemObservation
from .worktree import WorktreeManager


class BenchmarkSuite(Protocol):
    def plan(self, scenario: Any) -> SuitePlan: ...
    def evaluate(self, scenario: Any, observation: SystemObservation, oracle_context: Any) -> SuiteResult: ...


class SystemAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    execution_boundary: str

    def invoke(self, invocation: Any, run_context: "RunContext") -> SystemObservation: ...
    def validate_system_binding(self, system: SystemUnderTest, implementation_path: Path, executable_path: Path) -> bool: ...


class CheckpointMaterializer(Protocol):
    def apply(self, workspace: Path, scenario: Any, checkpoint_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class RunContext:
    workspace: Path
    temporary_directory: Path
    suite_id: str
    input_checkpoint: str
    input_fingerprint: str
    isolation_policy: IsolationPolicy


def _assert_public_invocation(value: object, path: str = "invocation") -> None:
    """Reject common hidden-oracle/seed leakage before crossing into the SUT."""
    forbidden = ("expected", "ground_truth", "oracle", "label", "seed", "mutation_parameter")
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            if any(token in item.name.casefold() for token in forbidden):
                raise ValueError(f"private benchmark field cannot enter SUT invocation: {path}.{item.name}")
            _assert_public_invocation(getattr(value, item.name), f"{path}.{item.name}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if any(token in name.casefold() for token in forbidden):
                raise ValueError(f"private benchmark field cannot enter SUT invocation: {path}.{name}")
            _assert_public_invocation(item, f"{path}.{name}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _assert_public_invocation(item, f"{path}[{index}]")


def _expected_overlays(scenario: ScenarioSpec, checkpoint_id: str) -> tuple[str, ...]:
    by_id = {item.checkpoint_id: item for item in scenario.checkpoints}
    ordered: list[str] = []
    seen: set[str] = set()
    def visit(current: str) -> None:
        if current in seen:
            return
        for parent in by_id[current].depends_on:
            visit(parent)
        ordered.extend(by_id[current].overlays)
        seen.add(current)
    visit(checkpoint_id)
    return tuple(ordered)


def _implementation_digest(value: object) -> str:
    target = value if inspect.isfunction(value) else type(value)
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        source = f"{target.__module__}.{target.__qualname__}"
    return str(Sha256Digest.of({"implementation": source}))


def _suite_result_from_json(payload: bytes) -> SuiteResult:
    value = json.loads(payload)
    oracles = tuple(OracleResult(**item) for item in value.pop("oracle_results"))
    stages = tuple(StageResult(**item) for item in value.pop("stage_results", ()))
    return SuiteResult(oracle_results=oracles, stage_results=stages, **value)


class ExperimentRunner:
    def __init__(
        self,
        worktrees: WorktreeManager,
        *,
        isolation_policy: IsolationPolicy | None = None,
        isolation_capabilities: IsolationCapabilities | None = None,
        cas: FileSystemCAS | None = None,
        process_runner: ProcessRunner | None = None,
        action_cache: ActionCache | None = None,
        sandbox_provider: SandboxProvider | None = None,
        sandbox_trust_store: SandboxTrustStore | None = None,
    ) -> None:
        self.worktrees = worktrees
        self.isolation_policy = isolation_policy or IsolationPolicy()
        self.isolation_capabilities = isolation_capabilities or local_process_capabilities()
        self.cas = cas
        self.process_runner = process_runner or ProcessRunner(capabilities=self.isolation_capabilities)
        self.action_cache = action_cache
        self.sandbox_provider = sandbox_provider
        self.last_evidence_receipt: str | None = None
        if self.isolation_policy.authoritative:
            if sandbox_trust_store is None:
                raise ValueError("authoritative runner requires an operator-owned sandbox trust store")
            resolved_provider = sandbox_trust_store.resolve(
                self.isolation_policy.trusted_provider_id or "", self.isolation_policy.trusted_provider_digest or "",
            )
            if sandbox_provider is not None and sandbox_provider is not resolved_provider:
                raise ValueError("caller-supplied sandbox provider differs from the operator trust store")
            self.sandbox_provider = resolved_provider
        if self.sandbox_provider is not None:
            attestation = self.sandbox_provider.attest()
            self.isolation_capabilities = attestation.capabilities
        if self.isolation_policy.authoritative and cas is None:
            raise ValueError("authoritative runner requires a CAS for mandatory evidence")

    def run_suite(
        self,
        *,
        snapshot: RepositorySnapshot,
        scenario: Any,
        suite: BenchmarkSuite,
        adapter: SystemAdapter,
        checkpoint_materializer: CheckpointMaterializer,
        invocation: Any,
        oracle_context: Any,
        seed: int,
        evidence: EvidenceBundleWriter | None = None,
        environment_digest: str | None = None,
        system_configuration: Mapping[str, object] | None = None,
        forced_fresh: bool = False,
        system: SystemUnderTest | None = None,
        baseline_health: tuple[BaselineHealth, ...] | None = None,
        evidence_receipt_path: str | Path | None = None,
        project: ProjectSpec | None = None,
        task: TaskSpec | None = None,
        system_implementation_path: str | Path | None = None,
        system_executable_path: str | Path | None = None,
        experiment: ExperimentSpec | None = None,
        attempt_index: int = 0,
    ) -> SuiteResult:
        validate_isolation(self.isolation_policy, self.isolation_capabilities)
        if self.isolation_policy.authoritative:
            if environment_digest is None:
                raise ValueError("authoritative run requires a pinned environment digest")
            if evidence is None or evidence_receipt_path is None:
                raise ValueError("authoritative run requires an evidence bundle and external receipt path")
            if not isinstance(project, ProjectSpec) or not isinstance(task, TaskSpec) or not isinstance(scenario, ScenarioSpec) or not isinstance(experiment, ExperimentSpec):
                raise ValueError("authoritative run requires typed project, task, and experiment identities")
            if not 0 <= attempt_index < experiment.attempts or experiment.seeds[attempt_index] != seed:
                raise ValueError("attempt index and seed do not match the immutable experiment")
            if experiment.project != project.identity or experiment.task != task.identity or experiment.scenario != scenario.identity or experiment.system != system:
                raise ValueError("experiment identities do not match the authoritative inputs")
            if str(experiment.environment_digest) != environment_digest:
                raise ValueError("experiment environment does not match the authoritative run")
            if scenario.project_id != project.project_id or scenario.task_id != task.task_id or task.project_id != project.project_id:
                raise ValueError("scenario, task, and project identities are not bound")
            if snapshot.commit != str(project.source.commit_sha) or str(snapshot.source_tree_digest) != str(project.source.source_tree_digest):
                raise ValueError("materialized repository does not match the pinned project")
            if not isinstance(system, SystemUnderTest):
                raise ValueError("authoritative run requires a pinned SystemUnderTest identity")
            implementation_digest = system.configuration.get("implementation_digest")
            executable_digest = system.configuration.get("executable_digest")
            if not isinstance(implementation_digest, str) or not isinstance(executable_digest, str):
                raise ValueError("authoritative SystemUnderTest requires implementation and executable digests")
            Sha256Digest(implementation_digest); Sha256Digest(executable_digest)
            if system_implementation_path is None or source_tree_digest(Path(system_implementation_path)) != implementation_digest:
                raise ValueError("launched production implementation does not match SystemUnderTest digest")
            executable_path = Path(system_executable_path or "").resolve()
            if not executable_path.is_file() or "sha256:" + hashlib.sha256(executable_path.read_bytes()).hexdigest() != executable_digest:
                raise ValueError("launched executable does not match SystemUnderTest digest")
            expected_system_id = getattr(adapter, "production_system_id", None)
            expected_system_version = getattr(adapter, "production_version", None)
            if expected_system_id is not None and expected_system_id != system.system_id:
                raise ValueError("adapter production system does not match SystemUnderTest")
            if expected_system_version is not None and expected_system_version != system.version:
                raise ValueError("adapter production version does not match SystemUnderTest")
            baseline_set = baseline_health if isinstance(baseline_health, tuple) else ()
            if len(baseline_set) != len(project.baseline.commands):
                raise ValueError("authoritative run requires a complete ordered baseline receipt")
            expected_attestation = str(Sha256Digest.of(self.sandbox_provider.attest()))
            for health, declared in zip(baseline_set, project.baseline.commands, strict=True):
                expected_argv = (str(Path(system_executable_path).resolve()), *declared.argv[1:]) if declared.argv[0] in {"python", "python3"} else declared.argv
                if not isinstance(health, BaselineHealth) or health.status is not RunStatus.PASS or not health.passed or not health.result.succeeded or not health.authoritative or health.result.argv != tuple(expected_argv):
                    raise ValueError("authoritative baseline receipt does not match a declared PASS command")
                try:
                    realized_command = CommandSpec(**dict(health.command_spec))
                except (TypeError, ValueError) as exc:
                    raise ValueError("baseline command receipt is malformed") from exc
                if realized_command.argv != tuple(expected_argv) or realized_command.timeout_seconds != declared.timeout_seconds:
                    raise ValueError("baseline command spec does not match the declared policy")
                if realized_command.cwd is None or source_tree_digest(Path(realized_command.cwd)) != str(project.source.source_tree_digest):
                    raise ValueError("baseline command cwd is not the pinned pristine project")
                if str(Sha256Digest.of(dict(health.command_spec))) != health.command_spec_digest:
                    raise ValueError("baseline command digest is inconsistent")
                expected_action_key = baseline_action_key(environment_digest, realized_command, project_digest=str(project.content_digest),
                    baseline_revision=project.baseline.baseline_health_revision, executor_version="3", test_policy_version="1", authoritative=True,
                    sandbox_attestation_digest=expected_attestation)
                if health.action_key != expected_action_key or health.executor_version != "3" or health.test_policy_version != "1" or health.baseline_revision != project.baseline.baseline_health_revision:
                    raise ValueError("baseline action, executor, or policy revision is not pinned")
                if health.project_digest != str(project.content_digest) or health.environment_fingerprint != environment_digest:
                    raise ValueError("baseline health identity does not match the authoritative run")
                if health.sandbox_attestation_digest != expected_attestation or not health.evidence_digest.startswith("cas:sha256:"):
                    raise ValueError("baseline sandbox evidence does not match the execution provider")
                self.cas.verify(health.evidence_digest)
                baseline_payload = canonical_json({"argv": health.result.argv, "returncode": health.result.returncode,
                    "stdout": health.result.stdout, "stderr": health.result.stderr, "timed_out": health.result.timed_out}).encode("utf-8")
                if FileSystemCAS.ref_for(baseline_payload) != health.evidence_digest:
                    raise ValueError("baseline result does not match its CAS execution evidence")
            Sha256Digest(environment_digest)
        plan = suite.plan(scenario)
        if self.isolation_policy.authoritative:
            if not isinstance(scenario, ScenarioSpec):
                raise ValueError("authoritative run requires a typed ScenarioSpec")
            if plan.suite_id not in scenario.suite_ids or plan not in experiment.suites:
                raise ValueError("suite plan is not declared by the pinned scenario and experiment")
            if plan.input_checkpoint not in {item.checkpoint_id for item in scenario.checkpoints}:
                raise ValueError("suite input checkpoint is not declared by the pinned scenario")
        scenario_execution = getattr(scenario, "execution", None)
        if scenario_execution is not None:
            scenario_mode = getattr(getattr(scenario_execution, "mode", None), "value", getattr(scenario_execution, "mode", None))
            policy_mode = getattr(self.isolation_policy.execution_mode, "value", self.isolation_policy.execution_mode)
            scenario_network = getattr(scenario_execution, "environment", {}).get("network")
            policy_network = getattr(self.isolation_policy.network, "value", self.isolation_policy.network)
            if scenario_mode != policy_mode or scenario_network != policy_network:
                raise ValueError("scenario execution mode/network conflicts with runner isolation policy")
        elif self.isolation_policy.authoritative:
            raise ValueError("authoritative run requires pinned scenario execution policy")
        if adapter.adapter_id != plan.adapter_id:
            raise ValueError(f"adapter mismatch: plan requires {plan.adapter_id}, got {adapter.adapter_id}")
        if adapter.adapter_version != plan.adapter_version:
            raise ValueError(f"adapter version mismatch: plan requires {plan.adapter_version}, got {adapter.adapter_version}")
        if self.isolation_policy.authoritative and not (
            callable(getattr(adapter, "prepare_command", None))
            and callable(getattr(adapter, "parse_execution", None))
            and callable(getattr(adapter, "validate_system_binding", None))
        ):
            raise ValueError("authoritative evaluation requires a bound runner-owned command adapter")
        if self.isolation_policy.authoritative and not adapter.validate_system_binding(system, Path(system_implementation_path), Path(system_executable_path)):
            raise ValueError("adapter rejected the pinned production implementation/API binding")
        _assert_public_invocation(invocation)
        if self.isolation_policy.authoritative and plan.labels_ref != "none":
            if getattr(oracle_context, "labels_ref", None) != plan.labels_ref:
                raise ValueError("private oracle context does not match the suite labels_ref")
            if plan.suite_id == "auto_refactoring" and (
                getattr(oracle_context, "oracle_id", None) != task.functional_oracle_ref.oracle_id
                or getattr(oracle_context, "oracle_version", None) != task.functional_oracle_ref.version
            ):
                raise ValueError("functional oracle implementation does not match the pinned task oracle")
        started = datetime.now(timezone.utc).isoformat()
        with self.worktrees.disposable(snapshot) as worktree:
            self.worktrees.verify_pristine(worktree, expected_source_tree_digest=snapshot.source_tree_digest)
            materialization_record = checkpoint_materializer.apply(worktree.path, scenario, plan.input_checkpoint)
            if self.isolation_policy.authoritative:
                expected_overlays = _expected_overlays(scenario, plan.input_checkpoint)
                expected_mechanics = scenario.metadata.get("mechanics_identities", {})
                if (
                    not isinstance(materialization_record, MaterializationRecord)
                    or materialization_record.checkpoint_id != plan.input_checkpoint
                    or materialization_record.applied_overlays != expected_overlays
                    or not isinstance(expected_mechanics, Mapping)
                    or set(materialization_record.mechanics_identities) != set(expected_overlays)
                    or any(materialization_record.mechanics_identities.get(name) != expected_mechanics.get(name) for name in expected_overlays)
                ):
                    raise ValueError("authoritative materialization does not prove exact ancestry and mechanics")
            materialization_evidence_ref = None
            if self.cas is not None:
                materialization_evidence_ref = self.cas.put_bytes(canonical_json(materialization_record).encode("utf-8"))
            input_digest = source_tree_digest(worktree.path)
            with tempfile.TemporaryDirectory(prefix="benchmark-run-", dir=self.worktrees.runs_root) as temporary:
                context = RunContext(
                    workspace=worktree.path,
                    temporary_directory=Path(temporary),
                    suite_id=plan.suite_id,
                    input_checkpoint=plan.input_checkpoint,
                    input_fingerprint=input_digest,
                    isolation_policy=self.isolation_policy,
                )
                cache_key = None
                cached_payload = None
                if self.action_cache is not None and getattr(adapter, "read_only", False):
                    adapter_configuration = {
                        "command": getattr(adapter, "command", None),
                        "timeout_seconds": getattr(adapter, "timeout_seconds", None),
                        "module_name": getattr(adapter, "module_name", None),
                        "environment": getattr(adapter, "environment", None),
                        "runner_executor_version": "3",
                        "sandbox_attestation": self.sandbox_provider.attest() if self.sandbox_provider is not None else None,
                    }
                    cache_key = observation_action_key(
                        input_checkpoint_digest=input_digest, invocation=invocation,
                        system_commit=str(system.commit_sha) if system is not None else snapshot.commit,
                        system_configuration=system.configuration if system is not None else (system_configuration or {}),
                        environment_digest=environment_digest or str(Sha256Digest.of({"non_authoritative": True})),
                        isolation_policy=self.isolation_policy, resource_policy={"timeout_seconds": getattr(scenario_execution, "timeout_seconds", None)},
                        adapter_id=adapter.adapter_id, adapter_version=adapter.adapter_version,
                        adapter_configuration=adapter_configuration, model_provider=None, model_id=None,
                        prompt_version="none", policy_version=plan.policy_version, tools=(), seed=seed,
                        execution_mode=getattr(getattr(scenario_execution, "mode", None), "value", "unspecified"),
                    )
                    if not forced_fresh:
                        cached_payload = self.action_cache.get_bytes(cache_key)
                if cached_payload is not None:
                    observation = SystemObservation(**json.loads(cached_payload))
                elif self.isolation_policy.authoritative:
                    command = adapter.prepare_command(invocation, context)
                    if not isinstance(command, CommandSpec):
                        raise TypeError("prepare_command must return CommandSpec")
                    if Path(command.argv[0]).resolve() != Path(system_executable_path).resolve():
                        raise ValueError("adapter command executable does not match pinned SystemUnderTest executable")
                    scenario_timeout = getattr(scenario_execution, "timeout_seconds", None)
                    if scenario_timeout is None:
                        raise ValueError("authoritative run requires a scenario timeout")
                    command_cwd = Path(command.cwd or worktree.path).resolve()
                    try:
                        command_cwd.relative_to(worktree.path.resolve())
                    except ValueError as exc:
                        raise ValueError("authoritative command cwd must remain inside the isolated worktree") from exc
                    command_environment = dict(command.environment)
                    command_environment.update({
                        "TMP": str(context.temporary_directory), "TEMP": str(context.temporary_directory), "TMPDIR": str(context.temporary_directory),
                        "AUTODEV_BOUND_EXECUTABLE": str(Path(system_executable_path).resolve()),
                        "AUTODEV_BOUND_IMPLEMENTATION": str(Path(system_implementation_path).resolve()),
                    })
                    command = replace(command, timeout_seconds=float(scenario_timeout), cwd=str(command_cwd), environment=command_environment)
                    execution = (
                        self.sandbox_provider.run(command, policy=self.isolation_policy)
                        if self.isolation_policy.authoritative else
                        self.process_runner.run(command, policy=self.isolation_policy)
                    )
                    observation = adapter.parse_execution(execution)
                else:
                    observation = adapter.invoke(invocation, context)
                if cache_key is not None and cached_payload is None:
                    self.action_cache.put_bytes(cache_key, canonical_json(observation).encode("utf-8"))
            output_digest = source_tree_digest(worktree.path)
            if observation.changed_tree_digest is None:
                observation = replace(observation, changed_tree_digest=output_digest)
            elif str(observation.changed_tree_digest) != output_digest:
                raise ValueError("adapter changed-tree claim does not match independently captured workspace")
            observation_evidence_ref = None
            if self.cas is not None:
                observation_evidence_ref = self.cas.put_bytes(canonical_json(observation).encode("utf-8"))
                if observation.output_artifact is None:
                    observation = replace(observation, output_artifact=observation_evidence_ref)
            resolved_oracle_context = (
                oracle_context(worktree.path, observation) if callable(oracle_context) else oracle_context
            )
            oracle_binding = None
            if self.isolation_policy.authoritative:
                oracle_binding = {
                    "labels_digest": str(Sha256Digest.of(resolved_oracle_context)),
                    "oracle_implementation_digest": _implementation_digest(oracle_context),
                }
                if experiment.oracle_bindings.get(plan.suite_id) != oracle_binding:
                    raise ValueError("oracle labels or implementation do not match the immutable experiment")
            oracle_cache_key = None
            cached_suite = None
            if self.action_cache is not None:
                private_context_digest = str(Sha256Digest.of(resolved_oracle_context))
                oracle_cache_key = oracle_action_key(
                    observation_digest=str(observation.content_digest), plan_digest=str(plan.content_digest),
                    oracle_id="suite-evaluation",
                    oracle_version=str(Sha256Digest.of(plan.oracle_ids)), suite_id=plan.suite_id,
                    suite_version=plan.suite_version, policy_version=plan.policy_version,
                    private_context_digest=private_context_digest,
                )
                if not forced_fresh:
                    cached_suite = self.action_cache.get_bytes(oracle_cache_key)
            suite_result = (
                _suite_result_from_json(cached_suite) if cached_suite is not None
                else suite.evaluate(scenario, observation, resolved_oracle_context)
            )
            if cached_suite is not None:
                for oracle in suite_result.oracle_results:
                    for ref in oracle.evidence_refs:
                        self.action_cache.cas.verify(ref)
            if self.cas is not None:
                evidenced_oracles = []
                for oracle in suite_result.oracle_results:
                    if oracle.evidence_refs:
                        evidenced_oracles.append(oracle)
                    else:
                        ref = self.cas.put_bytes(canonical_json(oracle).encode("utf-8"))
                        evidenced_oracles.append(replace(oracle, evidence_refs=(ref,)))
                suite_result = replace(suite_result, oracle_results=tuple(evidenced_oracles))
            if oracle_cache_key is not None and cached_suite is None and not suite_result.stage_results:
                self.action_cache.put_bytes(oracle_cache_key, canonical_json(suite_result).encode("utf-8"))
            platform_global_gates = dict(suite_result.global_gate_outcomes)
            platform_gate_evidence: dict[str, str] = {}
            if self.isolation_policy.authoritative and self.cas is not None and materialization_evidence_ref is not None:
                platform_gate_evidence["half_applied_transaction"] = self.cas.put_bytes(canonical_json({
                    "verifier": "exact-materialization-ancestry-v1", "materialization": materialization_evidence_ref,
                    "expected_overlays": _expected_overlays(scenario, plan.input_checkpoint),
                    "observed_overlays": materialization_record.applied_overlays,
                }).encode("utf-8"))
                platform_gate_evidence["accepted_stale_candidate"] = self.cas.put_bytes(canonical_json({
                    "verifier": "input-key-and-output-tree-v1", "input_digest": input_digest,
                    "observation_action_key": cache_key, "output_digest": output_digest,
                    "claimed_output_digest": str(observation.changed_tree_digest), "forced_fresh": forced_fresh,
                }).encode("utf-8"))
                platform_gate_evidence["evidence_integrity_failure"] = self.cas.put_bytes(canonical_json({
                    "verifier": "strict-bundle-external-receipt-v1", "bundle": str(evidence.directory.resolve()),
                    "receipt": str(Path(evidence_receipt_path).resolve()),
                }).encode("utf-8"))
            for gate_id in ("half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"):
                if gate_id in plan.global_hard_gate_ids:
                    platform_global_gates.setdefault(gate_id, gate_id in platform_gate_evidence)
            if platform_global_gates != dict(suite_result.global_gate_outcomes):
                platform_failures = list(suite_result.hard_gate_failures)
                platform_status = suite_result.status
                for gate_id in ("half_applied_transaction", "accepted_stale_candidate", "evidence_integrity_failure"):
                    if platform_global_gates.get(gate_id) is False and HardGate(gate_id) not in platform_failures:
                        platform_failures.append(HardGate(gate_id)); platform_status = RunStatus.FAIL
                suite_result = replace(suite_result, status=platform_status, hard_gate_failures=tuple(platform_failures), global_gate_outcomes=platform_global_gates)
            if suite_result.suite_id != plan.suite_id or suite_result.suite_version != plan.suite_version:
                raise ValueError("suite result identity does not match the immutable suite plan")
            actual_metrics, planned_metrics = set(suite_result.metrics), set(plan.metric_ids)
            if actual_metrics - planned_metrics or (suite_result.status is RunStatus.PASS and actual_metrics != planned_metrics):
                raise ValueError("suite result metrics do not match the immutable suite plan")
            if actual_metrics != planned_metrics:
                suite_result = replace(suite_result, metrics={name: suite_result.metrics.get(name) for name in plan.metric_ids})
            actual_oracles = {item.oracle_id for item in suite_result.oracle_results}
            required_oracles = set(plan.oracle_ids)
            if actual_oracles != required_oracles:
                raise ValueError(
                    "suite result oracle set mismatch: "
                    f"missing={sorted(required_oracles - actual_oracles)}, extra={sorted(actual_oracles - required_oracles)}"
                )
            if observation.status is not RunStatus.PASS and suite_result.status is RunStatus.PASS:
                raise ValueError("suite cannot PASS a non-PASS system observation")
            if set(suite_result.suite_gate_outcomes) != set(plan.hard_gate_ids):
                raise ValueError("suite-local gate outcomes do not match the immutable plan")
            if set(suite_result.global_gate_outcomes) != set(plan.global_hard_gate_ids):
                raise ValueError("global gate outcomes do not match the immutable plan")

        failures = list(suite_result.hard_gate_failures)
        missing = []
        for required in plan.required_observations:
            value = observation.attributes.get(required)
            if value is None and getattr(observation, required, None) is None:
                missing.append(required)
        status = suite_result.status
        if missing and HardGate.LOST_REQUIRED_VERIFICATION not in failures:
            failures.append(HardGate.LOST_REQUIRED_VERIFICATION)
            status = RunStatus.FAIL
        global_gate_outcomes = dict(suite_result.global_gate_outcomes)
        if missing and "lost_required_verification" in plan.global_hard_gate_ids:
            global_gate_outcomes["lost_required_verification"] = False
        completed = datetime.now(timezone.utc).isoformat()
        stage = StageResult(
            stage_id=f"{plan.suite_id}.execute",
            status=status,
            observation=observation,
            oracle_results=suite_result.oracle_results,
            details={"adapter_id": adapter.adapter_id, "adapter_version": adapter.adapter_version, "missing_observations": missing, "scenario_seed": seed},
            component=plan.suite_id,
            input_fingerprint=input_digest,
            output_fingerprint=output_digest,
            started_at=started,
            completed_at=completed,
            evidence_refs=tuple(
                ref for ref in (materialization_evidence_ref, observation_evidence_ref) if ref is not None
            ),
            failure_class="LOST_REQUIRED_VERIFICATION" if missing else None,
        )
        result = SuiteResult(
            suite_id=suite_result.suite_id,
            suite_version=suite_result.suite_version,
            status=status,
            oracle_results=suite_result.oracle_results,
            hard_gate_failures=tuple(failures),
            metrics=suite_result.metrics,
            stage_results=(*suite_result.stage_results, stage),
            suite_gate_outcomes=suite_result.suite_gate_outcomes,
            global_gate_outcomes=global_gate_outcomes,
        )
        if evidence is not None:
            evidence.add_stage(stage)
        if self.isolation_policy.authoritative:
            run_digest = str(Sha256Digest.of({"experiment": str(experiment.content_digest), "suite": plan.content_digest, "attempt": attempt_index, "seed": seed}))
            manifest = {
                "schema_version": "1", "run_id": "run_" + run_digest.removeprefix("sha256:"),
                "experiment_id": str(experiment.content_digest),
                "versions": {"benchmark_spec": experiment.spec_version},
                "input": {}, "system": {}, "scenario": {}, "suite_results": {}, "metrics": {},
                "provenance": {
                    "invocation_digest": str(Sha256Digest.of(invocation)),
                    "oracle_binding": oracle_binding,
                    "sandbox_attestation_digest": expected_attestation,
                    "baseline_evidence_digests": [health.evidence_digest for health in baseline_set],
                    "materialization_evidence_ref": materialization_evidence_ref,
                    "platform_gate_evidence": platform_gate_evidence,
                    "mechanics_identities": dict(materialization_record.mechanics_identities),
                    "attempt_index": attempt_index, "seed": seed,
                },
            }
            expected_versions = {
                "runner": "3", "adapter": plan.adapter_version, "suite": plan.suite_version,
                "policy": plan.policy_version, "acceptance": plan.acceptance_version,
            }
            manifest["versions"].update(expected_versions)
            expected_system = {
                "system_id": system.system_id,
                "commit": str(system.commit_sha),
                "configuration_digest": str(Sha256Digest.of(system.configuration)),
            }
            manifest["system"] = expected_system
            expected_scenario = {
                "scenario_id": scenario.scenario_id, "scenario_version": scenario.spec_version,
                "content_digest": str(scenario.content_digest),
            }
            manifest["scenario"] = expected_scenario
            expected_inputs = {
                "project_digest": str(project.content_digest), "task_digest": str(task.content_digest),
                "checkpoint_digest": input_digest, "environment_digest": environment_digest,
            }
            manifest["input"] = expected_inputs
            manifest["suite_results"] = {plan.suite_id: {
                "suite_version": result.suite_version, "status": result.status.value,
                "oracle_results": {oracle.oracle_id: {
                    "oracle_version": oracle.oracle_version, "status": oracle.status.value,
                    "evidence_refs": list(oracle.evidence_refs),
                } for oracle in result.oracle_results},
                "suite_gate_outcomes": dict(result.suite_gate_outcomes),
                "global_gate_outcomes": dict(result.global_gate_outcomes),
            }}
            manifest["metrics"] = dict(result.metrics)
            evidence.finalize(manifest)
            receipt = evidence.root_digest
            if receipt is None:
                raise ValueError("evidence writer did not produce an external root receipt")
            receipt_path = Path(evidence_receipt_path).resolve()
            try:
                receipt_path.relative_to(evidence.directory.resolve())
            except ValueError:
                pass
            else:
                raise ValueError("external evidence receipt must be stored outside the mutable bundle")
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with receipt_path.open("x", encoding="utf-8", newline="\n") as receipt_file:
                receipt_file.write(receipt + "\n")
            EvidenceBundleVerifier(evidence.cas).verify(evidence.directory, expected_root=receipt_path.read_text(encoding="utf-8").strip())
            self.last_evidence_receipt = receipt
        return result
