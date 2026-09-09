"""Authoritative admission validation for :mod:`benchmark_core.runner`.

This module owns the pre-execution proof that a requested benchmark run is
bound to the immutable experiment, exact production implementation, trusted
sandbox, and complete baseline evidence.  Keeping this logic out of the runner
lets ``ExperimentRunner`` remain an orchestration component rather than also
being the admission-policy authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .adapter_contracts import CommandSystemAdapter, require_command_system_adapter
from .cas import FileSystemCAS
from .checkout import RepositorySnapshot, source_tree_digest
from .environment import BaselineHealth, baseline_action_key
from .evidence import EvidenceBundleWriter
from .execution import CommandSpec, SandboxProvider
from .experiment import ExperimentSpec, SystemUnderTest
from .identity import Sha256Digest, canonical_json
from .isolation import IsolationPolicy
from .project import ProjectSpec
from .result import RunStatus
from .scenario import ScenarioSpec
from .task import TaskSpec


@dataclass(frozen=True, slots=True)
class AuthoritativeAdmission:
    """Validated dependencies consumed by the authoritative execution path."""

    adapter: CommandSystemAdapter
    baseline_set: tuple[BaselineHealth, ...]
    expected_attestation: str
    implementation_path: Path
    executable_path: Path


class AuthoritativeAdmissionValidator:
    """Fail-closed validator for immutable authoritative run inputs."""

    def __init__(
        self,
        *,
        isolation_policy: IsolationPolicy,
        cas: FileSystemCAS,
        sandbox_provider: SandboxProvider,
    ) -> None:
        self._isolation_policy = isolation_policy
        self._cas = cas
        self._sandbox_provider = sandbox_provider

    def validate(
        self,
        *,
        snapshot: RepositorySnapshot,
        scenario: object,
        adapter: object,
        seed: int,
        evidence: EvidenceBundleWriter | None,
        environment_digest: str | None,
        system: SystemUnderTest | None,
        baseline_health: tuple[BaselineHealth, ...] | None,
        evidence_receipt_path: str | Path | None,
        project: ProjectSpec | None,
        task: TaskSpec | None,
        system_implementation_path: str | Path | None,
        system_executable_path: str | Path | None,
        experiment: ExperimentSpec | None,
        attempt_index: int,
    ) -> AuthoritativeAdmission:
        if environment_digest is None:
            raise ValueError("authoritative run requires a pinned environment digest")
        if evidence is None or evidence_receipt_path is None:
            raise ValueError("authoritative run requires an evidence bundle and external receipt path")
        if (
            not isinstance(project, ProjectSpec)
            or not isinstance(task, TaskSpec)
            or not isinstance(scenario, ScenarioSpec)
            or not isinstance(experiment, ExperimentSpec)
        ):
            raise ValueError("authoritative run requires typed project, task, and experiment identities")
        if not isinstance(system, SystemUnderTest):
            raise ValueError("authoritative run requires a pinned SystemUnderTest identity")
        if not 0 <= attempt_index < experiment.attempts or experiment.seeds[attempt_index] != seed:
            raise ValueError("attempt index and seed do not match the immutable experiment")
        if (
            experiment.project != project.identity
            or experiment.task != task.identity
            or experiment.scenario != scenario.identity
            or experiment.system != system
        ):
            raise ValueError("experiment identities do not match the authoritative inputs")
        if str(experiment.environment_digest) != environment_digest:
            raise ValueError("experiment environment does not match the authoritative run")
        if scenario.project_id != project.project_id or scenario.task_id != task.task_id or task.project_id != project.project_id:
            raise ValueError("scenario, task, and project identities are not bound")
        if snapshot.commit != str(project.source.commit_sha) or str(snapshot.source_tree_digest) != str(project.source.source_tree_digest):
            raise ValueError("materialized repository does not match the pinned project")

        implementation_path = Path(system_implementation_path or "").resolve()
        executable_path = Path(system_executable_path or "").resolve()
        implementation_digest = system.configuration.get("implementation_digest")
        executable_digest = system.configuration.get("executable_digest")
        if not isinstance(implementation_digest, str) or not isinstance(executable_digest, str):
            raise ValueError("authoritative SystemUnderTest requires implementation and executable digests")
        Sha256Digest(implementation_digest)
        Sha256Digest(executable_digest)
        if system_implementation_path is None or source_tree_digest(implementation_path) != implementation_digest:
            raise ValueError("launched production implementation does not match SystemUnderTest digest")
        if not executable_path.is_file() or "sha256:" + hashlib.sha256(executable_path.read_bytes()).hexdigest() != executable_digest:
            raise ValueError("launched executable does not match SystemUnderTest digest")

        command_adapter = require_command_system_adapter(adapter)
        if command_adapter.production_system_id != system.system_id:
            raise ValueError("adapter production system does not match SystemUnderTest")
        if command_adapter.production_version != system.version:
            raise ValueError("adapter production version does not match SystemUnderTest")
        if not command_adapter.validate_system_binding(system, implementation_path, executable_path):
            raise ValueError("adapter rejected the pinned production implementation/API binding")

        baseline_set = baseline_health if isinstance(baseline_health, tuple) else ()
        if len(baseline_set) != len(project.baseline.commands):
            raise ValueError("authoritative run requires a complete ordered baseline receipt")
        expected_attestation = str(Sha256Digest.of(self._sandbox_provider.attest()))
        for health, declared in zip(baseline_set, project.baseline.commands, strict=True):
            expected_argv = (
                (str(executable_path), *declared.argv[1:])
                if declared.argv[0] in {"python", "python3"}
                else declared.argv
            )
            if (
                not isinstance(health, BaselineHealth)
                or health.status is not RunStatus.PASS
                or not health.passed
                or not health.result.succeeded
                or not health.authoritative
                or health.result.argv != tuple(expected_argv)
            ):
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
            expected_action_key = baseline_action_key(
                environment_digest,
                realized_command,
                project_digest=str(project.content_digest),
                baseline_revision=project.baseline.baseline_health_revision,
                executor_version="3",
                test_policy_version="1",
                authoritative=True,
                sandbox_attestation_digest=expected_attestation,
            )
            if (
                health.action_key != expected_action_key
                or health.executor_version != "3"
                or health.test_policy_version != "1"
                or health.baseline_revision != project.baseline.baseline_health_revision
            ):
                raise ValueError("baseline action, executor, or policy revision is not pinned")
            if health.project_digest != str(project.content_digest) or health.environment_fingerprint != environment_digest:
                raise ValueError("baseline health identity does not match the authoritative run")
            if health.sandbox_attestation_digest != expected_attestation or not health.evidence_digest.startswith("cas:sha256:"):
                raise ValueError("baseline sandbox evidence does not match the execution provider")
            self._cas.verify(health.evidence_digest)
            baseline_payload = canonical_json(
                {
                    "argv": health.result.argv,
                    "returncode": health.result.returncode,
                    "stdout": health.result.stdout,
                    "stderr": health.result.stderr,
                    "timed_out": health.result.timed_out,
                }
            ).encode("utf-8")
            if FileSystemCAS.ref_for(baseline_payload) != health.evidence_digest:
                raise ValueError("baseline result does not match its CAS execution evidence")

        Sha256Digest(environment_digest)
        return AuthoritativeAdmission(
            adapter=command_adapter,
            baseline_set=baseline_set,
            expected_attestation=expected_attestation,
            implementation_path=implementation_path,
            executable_path=executable_path,
        )
