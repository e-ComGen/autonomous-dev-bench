"""Exact virtual-environment bootstrap and baseline admission for pinned projects."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import posixpath
import platform
import shutil
import subprocess
import sys

from .cache import ActionCache
from .cas import FileSystemCAS
from .checkout import source_tree_digest
from .environment import BaselineHealth, BaselineHealthRunner, EnvironmentFingerprint
from .execution import CommandSpec, ExecutionResult, ProcessRunner, SandboxProvider
from .isolation import IsolationPolicy, NetworkPolicy, SandboxTrustStore, validate_isolation
from .identity import Sha256Digest, canonical_json
from .project import ProjectSpec
from .result import RunStatus


ENVIRONMENT_BUILDER_VERSION = "3"


@dataclass(frozen=True)
class EnvironmentBuildResult:
    status: RunStatus
    environment: EnvironmentFingerprint | None
    python_executable: str | None
    bootstrap_result: ExecutionResult | None
    baseline_health: tuple[BaselineHealth, ...]
    evidence_refs: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return self.status is RunStatus.PASS and bool(self.baseline_health) and all(item.status is RunStatus.PASS for item in self.baseline_health)


class _SandboxRunner:
    def __init__(self, provider: SandboxProvider, policy: IsolationPolicy, output_root: Path) -> None:
        self.provider, self.policy, self.output_root = provider, policy, output_root
    def run(self, command: CommandSpec) -> ExecutionResult:
        environment = dict(command.environment)
        environment.update({"AUTODEV_BUILD_WORKSPACE": str(Path(command.cwd or ".").resolve()),
                            "AUTODEV_BUILD_OUTPUT": str(self.output_root.resolve())})
        return self.provider.run(replace(command, environment=environment), policy=self.policy)


class ProjectEnvironmentBuilder:
    """Build a pinned venv, capture provenance, and prove every baseline command green."""

    def __init__(self, root: str | Path, cas: FileSystemCAS, *, cache: ActionCache | None = None,
                 process_runner: ProcessRunner | None = None, executor_version: str = "3", test_policy_version: str = "1",
                 sandbox_provider: SandboxProvider | None = None, isolation_policy: IsolationPolicy | None = None,
                 sandbox_trust_store: SandboxTrustStore | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cas = cas
        self.cache = cache
        self.runner = process_runner or ProcessRunner()
        self.isolation_policy = isolation_policy or IsolationPolicy(authoritative=False, fresh_worktree=False, network=NetworkPolicy.PACKAGE_INDICES_ONLY)
        self.sandbox_provider = sandbox_provider
        self.sandbox_attestation_digest: str | None = None
        self.authoritative = self.isolation_policy.authoritative
        if self.authoritative:
            if cache is None:
                raise ValueError("authoritative environment build requires a CAS-backed action cache")
            if sandbox_trust_store is None:
                raise ValueError("authoritative environment build requires an operator-owned sandbox trust store")
            resolved_provider = sandbox_trust_store.resolve(
                self.isolation_policy.trusted_provider_id or "", self.isolation_policy.trusted_provider_digest or "",
            )
            if sandbox_provider is not None and sandbox_provider is not resolved_provider:
                raise ValueError("caller-supplied build provider differs from the operator trust store")
            self.sandbox_provider = resolved_provider
            attestation = resolved_provider.attest()
            validate_isolation(self.isolation_policy, attestation.capabilities)
            self.sandbox_attestation_digest = str(Sha256Digest.of(attestation))
            self.runner = _SandboxRunner(resolved_provider, self.isolation_policy, self.root)
        self.executor_version = executor_version
        self.test_policy_version = test_policy_version

    @staticmethod
    def _restore_pristine(workspace: Path, expected_digest: str) -> None:
        probe = subprocess.run(("git", "-C", str(workspace), "rev-parse", "--is-inside-work-tree"), capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            subprocess.run(("git", "-C", str(workspace), "reset", "--hard", "HEAD"), capture_output=True, check=True)
            subprocess.run(("git", "-C", str(workspace), "clean", "-ffdx"), capture_output=True, check=True)
            listing = subprocess.run(("git", "-C", str(workspace), "ls-tree", "-r", "-z", "--full-tree", "HEAD"),
                                     check=True, stdout=subprocess.PIPE).stdout
            entries = [entry for entry in listing.split(b"\0") if entry]
            tracked_paths = {entry.split(b"\t", 1)[1].decode("utf-8", "surrogateescape") for entry in entries}
            for entry in entries:
                metadata, raw_path = entry.split(b"\t", 1)
                mode, kind, object_id = metadata.split(b" ", 2)
                if kind != b"blob": raise ValueError("baseline restore only supports Git blobs")
                relative = Path(raw_path.decode("utf-8", "surrogateescape"))
                if relative.is_absolute() or ".." in relative.parts: raise ValueError("Git tree path escapes workspace")
                target = workspace / relative
                payload = subprocess.run(("git", "-C", str(workspace), "cat-file", "blob", object_id.decode("ascii")),
                                         check=True, stdout=subprocess.PIPE).stdout
                if target.exists() or target.is_symlink(): target.unlink()
                if mode == b"120000":
                    link_target = payload.decode("utf-8", "surrogateescape")
                    resolved_target = posixpath.normpath(posixpath.join(posixpath.dirname(relative.as_posix()), link_target))
                    target_is_directory = any(item.startswith(resolved_target.rstrip("/") + "/") for item in tracked_paths)
                    try:
                        target.symlink_to(link_target.replace("/", os.sep), target_is_directory=target_is_directory)
                        expected_target = (target.parent / link_target).resolve(strict=False)
                        if expected_target.exists() and not target.exists():
                            target.unlink()
                            target.symlink_to(expected_target, target_is_directory=target_is_directory)
                    except OSError as exc: raise ValueError(f"cannot restore pinned symlink: {relative.as_posix()}") from exc
                else:
                    target.write_bytes(payload)
                    if mode == b"100755": target.chmod(target.stat().st_mode | 0o111)
        if source_tree_digest(workspace) != expected_digest:
            raise ValueError("baseline execution did not restore the disposable source tree")

    def build_and_verify(self, project: ProjectSpec, workspace: str | Path) -> EnvironmentBuildResult:
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError("workspace must exist")
        actual_source_digest = source_tree_digest(workspace)
        if actual_source_digest != str(project.source.source_tree_digest):
            raise ValueError("bootstrap workspace does not match the pinned project source tree")
        verified_dependency_specs: list[tuple[str, str]] = []
        for relative, expected in zip(project.bootstrap.dependency_spec_paths, project.bootstrap.dependency_spec_digests, strict=True):
            dependency_file = workspace / relative
            if not dependency_file.is_file():
                raise ValueError(f"missing pinned dependency specification: {relative}")
            actual = "sha256:" + hashlib.sha256(dependency_file.read_bytes()).hexdigest()
            if actual != str(expected):
                raise ValueError(f"dependency specification digest mismatch: {relative}")
            verified_dependency_specs.append((relative, actual))
        bootstrap_key = str(Sha256Digest.of({
            "builder_version": ENVIRONMENT_BUILDER_VERSION,
            "source": project.source.content_digest, "bootstrap": project.bootstrap, "host_python": sys.version,
            "isolation_policy": self.isolation_policy,
            "sandbox_attestation": self.sandbox_provider.attest() if self.sandbox_provider is not None else None,
        }))
        environment_root = self.root / bootstrap_key.removeprefix("sha256:")
        python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        marker = environment_root / ".autodev-bootstrap.json"
        bootstrap_result: ExecutionResult | None = None
        evidence: list[str] = []
        if not python.is_file() or not marker.is_file() or marker.read_text(encoding="utf-8") != bootstrap_key:
            shutil.rmtree(environment_root, ignore_errors=True)
            create_result = self.runner.run(CommandSpec((sys.executable, "-m", "venv", str(environment_root)), 300, str(workspace), {}))
            evidence.append(self.cas.put_bytes(canonical_json(create_result).encode("utf-8")))
            if not create_result.succeeded:
                return EnvironmentBuildResult(RunStatus.INFRA_FAILURE, None, None, create_result, (), tuple(evidence))
            install = project.bootstrap.install
            if install is not None:
                argv = list(install.argv)
                if argv[0] in {"python", "python3", sys.executable}:
                    argv[0] = str(python)
                bootstrap_result = self.runner.run(CommandSpec(tuple(argv), install.timeout_seconds, str(workspace), {str(k): str(v) for k, v in install.environment.items()}))
                evidence.append(self.cas.put_bytes(canonical_json(bootstrap_result).encode("utf-8")))
                if not bootstrap_result.succeeded:
                    self._restore_pristine(workspace, str(project.source.source_tree_digest))
                    return EnvironmentBuildResult(RunStatus.INFRA_FAILURE, None, str(python), bootstrap_result, (), tuple(evidence))
            marker.write_text(bootstrap_key, encoding="utf-8")
        freeze = self.runner.run(CommandSpec((str(python), "-m", "pip", "freeze", "--all"), 120, str(workspace), {}))
        pip_version = self.runner.run(CommandSpec((str(python), "-m", "pip", "--version"), 60, str(workspace), {}))
        evidence.extend((self.cas.put_bytes(canonical_json(freeze).encode("utf-8")), self.cas.put_bytes(canonical_json(pip_version).encode("utf-8"))))
        if not freeze.succeeded or not pip_version.succeeded:
            return EnvironmentBuildResult(RunStatus.INFRA_FAILURE, None, str(python), bootstrap_result, (), tuple(evidence))
        executable_digest = "sha256:" + hashlib.sha256(python.read_bytes()).hexdigest()
        lock_digest = str(Sha256Digest.of(tuple(verified_dependency_specs)))
        environment = EnvironmentFingerprint(
            str(project.source.source_tree_digest), str(project.source.commit_sha), platform.system().lower(), platform.version(), platform.machine(),
            platform.python_implementation(), platform.python_version(), executable_digest, lock_digest,
            project.bootstrap.extras, "pip", pip_version.stdout.strip(), str(Sha256Digest.of(freeze.stdout)),
            project.bootstrap.adapter_id, ENVIRONMENT_BUILDER_VERSION, tuple(sorted((name, os.environ.get(name, "")) for name in ("LANG", "TZ", "PYTHONHASHSEED"))),
            project.security.build_network_policy, project.security.execution_network_policy, str(project.bootstrap.content_digest),
        )
        health: list[BaselineHealth] = []
        baseline_runner = BaselineHealthRunner(self.runner, executor_version=self.executor_version,
            test_policy_version=self.test_policy_version, baseline_revision=project.baseline.baseline_health_revision, cache=self.cache,
            authoritative=self.authoritative, sandbox_attestation_digest=self.sandbox_attestation_digest)
        for declared in project.baseline.commands:
            argv = list(declared.argv)
            if argv[0] in {"python", "python3", sys.executable}:
                argv[0] = str(python)
            command = CommandSpec(tuple(argv), declared.timeout_seconds, str(workspace), {str(k): str(v) for k, v in declared.environment.items()})
            item = baseline_runner.run(str(project.content_digest), environment, command)
            health.append(item)
            evidence.append(self.cas.put_bytes(canonical_json(item).encode("utf-8")))
            if item.status is not RunStatus.PASS:
                self._restore_pristine(workspace, str(project.source.source_tree_digest))
                return EnvironmentBuildResult(item.status, environment, str(python), bootstrap_result, tuple(health), tuple(evidence))
        self._restore_pristine(workspace, str(project.source.source_tree_digest))
        return EnvironmentBuildResult(RunStatus.PASS, environment, str(python), bootstrap_result, tuple(health), tuple(evidence))
