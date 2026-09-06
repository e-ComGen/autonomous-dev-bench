"""Complete environment identities and baseline health execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import re
from pathlib import Path
import sys
from typing import Mapping

from .cache import ActionCache
from .identity import canonical_json, freeze_json, FrozenDict, Sha256Digest


def _content_digest(value: object) -> str:
    return str(Sha256Digest.of(value))
from .execution import CommandSpec, ExecutionResult, ProcessRunner
from .result import RunStatus


@dataclass(frozen=True)
class EnvironmentFingerprint:
    project_source_digest: str
    repository_commit: str
    os_family: str
    os_version: str
    architecture: str
    interpreter_implementation: str
    interpreter_version: str
    interpreter_executable_digest: str
    dependency_lock_digest: str
    dependency_extras: tuple[str, ...] = ()
    installer_name: str = "stdlib"
    installer_version: str = ""
    system_dependencies_digest: str = "sha256:" + "0" * 64
    adapter_id: str = "python-standard"
    adapter_version: str = "1"
    relevant_variables: tuple[tuple[str, str], ...] = ()
    build_network_policy: str = "package_indices_only"
    run_network_policy: str = "none"
    bootstrap_spec_digest: str = "sha256:" + "0" * 64

    def __post_init__(self) -> None:
        for name in (
            "project_source_digest", "interpreter_executable_digest", "dependency_lock_digest",
            "system_dependencies_digest", "bootstrap_spec_digest",
        ):
            Sha256Digest(getattr(self, name))
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", self.repository_commit):
            raise ValueError("repository_commit must be a full lowercase Git object id")
        extras = tuple(self.dependency_extras)
        if len(extras) != len(set(extras)) or any(not isinstance(item, str) or not item for item in extras):
            raise ValueError("dependency_extras must be unique non-empty strings")
        variables = tuple(sorted(tuple(item) for item in self.relevant_variables))
        if any(len(item) != 2 or not all(isinstance(value, str) for value in item) for item in variables):
            raise ValueError("relevant_variables must contain string pairs")
        if len({name for name, _ in variables}) != len(variables):
            raise ValueError("relevant_variables must not repeat names")
        if self.run_network_policy not in {"none", "package_indices_only", "unrestricted"}:
            raise ValueError("invalid run_network_policy")
        object.__setattr__(self, "dependency_extras", extras)
        object.__setattr__(self, "relevant_variables", variables)

    @property
    def digest(self) -> str:
        return _content_digest(asdict(self))

    @classmethod
    def current(cls, *, project_source_digest: str, repository_commit: str,
                dependency_lock_digest: str, dependency_extras: tuple[str, ...] = (),
                relevant_variable_names: tuple[str, ...] = ("LANG", "TZ", "PYTHONHASHSEED"),
                **overrides: object) -> "EnvironmentFingerprint":
        executable = Path(sys.executable)
        executable_digest = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
        values: dict[str, object] = dict(
            project_source_digest=project_source_digest, repository_commit=repository_commit,
            os_family=platform.system().lower(), os_version=platform.version(), architecture=platform.machine(),
            interpreter_implementation=platform.python_implementation(), interpreter_version=platform.python_version(),
            interpreter_executable_digest=executable_digest, dependency_lock_digest=dependency_lock_digest,
            dependency_extras=dependency_extras,
            relevant_variables=tuple(sorted((name, os.environ.get(name, "")) for name in relevant_variable_names)),
        )
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class BaselineHealth:
    project_digest: str
    environment_fingerprint: str
    command_spec_digest: str
    executor_version: str
    test_policy_version: str
    baseline_revision: str
    last_verified_at: str
    passed: bool
    status: RunStatus
    result: ExecutionResult
    evidence_digest: str
    action_key: str
    authoritative: bool = False
    sandbox_attestation_digest: str | None = None
    command_spec: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if self.authoritative:
            if self.sandbox_attestation_digest is None:
                raise ValueError("authoritative baseline requires a sandbox attestation digest")
            Sha256Digest(self.sandbox_attestation_digest)
        object.__setattr__(self, "command_spec", freeze_json(self.command_spec))


def baseline_action_key(environment: EnvironmentFingerprint | str, command: CommandSpec,
                        *, project_digest: str, baseline_revision: str,
                        executor_version: str, test_policy_version: str, authoritative: bool = False,
                        sandbox_attestation_digest: str | None = None) -> str:
    env_digest = environment.digest if isinstance(environment, EnvironmentFingerprint) else environment
    return _content_digest({"project_digest": project_digest, "baseline_revision": baseline_revision,
                           "environment_fingerprint": env_digest,
                           "command": {"argv": command.argv, "timeout_seconds": command.timeout_seconds,
                                       "cwd": command.cwd, "environment": dict(sorted(command.environment.items())),
                                       "stdin": command.stdin},
                           "executor_version": executor_version, "test_policy_version": test_policy_version,
                           "authoritative": authoritative,
                           "sandbox_attestation_digest": sandbox_attestation_digest})


class BaselineHealthRunner:
    def __init__(self, runner: ProcessRunner | None = None, *, executor_version: str = "3",
                 test_policy_version: str = "1", baseline_revision: str = "1",
                 cache: ActionCache | None = None, authoritative: bool = False,
                 sandbox_attestation_digest: str | None = None) -> None:
        self.runner = runner or ProcessRunner()
        self.executor_version = executor_version
        self.test_policy_version = test_policy_version
        self.baseline_revision = baseline_revision
        self.cache = cache
        self.authoritative = authoritative
        self.sandbox_attestation_digest = sandbox_attestation_digest
        if authoritative:
            Sha256Digest(sandbox_attestation_digest)

    def run(self, project_digest: str, environment: EnvironmentFingerprint, command: CommandSpec) -> BaselineHealth:
        action_key = baseline_action_key(
            environment, command, project_digest=project_digest, baseline_revision=self.baseline_revision,
            executor_version=self.executor_version, test_policy_version=self.test_policy_version,
            authoritative=self.authoritative, sandbox_attestation_digest=self.sandbox_attestation_digest,
        )
        if self.cache is not None:
            cached = self.cache.get_bytes(action_key)
            if cached is not None:
                health = self._decode(cached)
                if health.evidence_digest.startswith("cas:sha256:"):
                    self.cache.cas.verify(health.evidence_digest)
                elif health.authoritative:
                    raise ValueError("cached authoritative baseline lacks CAS evidence")
                return health
        try:
            result = self.runner.run(command)
            status = RunStatus.PASS if result.succeeded else RunStatus.BASELINE_BROKEN
        except OSError as exc:
            result = ExecutionResult(tuple(command.argv), None, "", str(exc), False, 0.0)
            status = RunStatus.INFRA_FAILURE
        evidence_payload = canonical_json({"argv": result.argv, "returncode": result.returncode,
                                           "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out}).encode("utf-8")
        evidence = self.cache.cas.put_bytes(evidence_payload) if self.cache is not None else _content_digest(json.loads(evidence_payload))
        command_spec = {"argv": command.argv, "timeout_seconds": command.timeout_seconds,
                        "cwd": command.cwd, "environment": command.environment, "stdin": command.stdin}
        command_digest = _content_digest(command_spec)
        health = BaselineHealth(
            project_digest, environment.digest, command_digest, self.executor_version, self.test_policy_version,
            self.baseline_revision, datetime.now(timezone.utc).isoformat(), status is RunStatus.PASS, status, result, evidence, action_key,
            self.authoritative, self.sandbox_attestation_digest, command_spec,
        )
        if self.cache is not None:
            self.cache.put_bytes(action_key, self._encode(health))
        return health

    @staticmethod
    def _encode(health: BaselineHealth) -> bytes:
        value = asdict(health)
        value["status"] = health.status.value
        return canonical_json(value).encode("utf-8")

    @staticmethod
    def _decode(payload: bytes) -> BaselineHealth:
        value = json.loads(payload)
        result = ExecutionResult(**value.pop("result"))
        value["status"] = RunStatus(value["status"])
        return BaselineHealth(result=result, **value)
