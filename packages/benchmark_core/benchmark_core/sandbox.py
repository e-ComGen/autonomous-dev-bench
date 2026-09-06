"""Concrete container sandbox provider for authoritative offline execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .execution import CommandSpec, ExecutionResult, ProcessRunner
from .isolation import IsolationCapabilities, IsolationPolicy, NetworkPolicy, SandboxAttestation, sandbox_provider_artifact_digest


_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class DockerSandboxProvider:
    """Run a command in a pinned, read-only Docker image with network denied.

    Package-index allowlisting is deliberately not claimed; builds needing network
    require a different attested provider. The workspace and benchmark temp
    directory are the only writable mounts.
    """

    image: str
    docker_executable: str = "docker"
    provider_id: str = "docker-offline"
    provider_version: str = "1"

    def __post_init__(self) -> None:
        if not _IMAGE.fullmatch(self.image):
            raise ValueError("Docker image must be pinned by sha256 digest")

    def attest(self) -> SandboxAttestation:
        implementation = sandbox_provider_artifact_digest(self)
        return SandboxAttestation(
            self.provider_id, self.provider_version, implementation,
            IsolationCapabilities(network_none=True, network_allowlist=False, fresh_process=True,
                                  process_tree_cleanup=True, filesystem_isolation=True),
        )

    def _run_build(self, command: CommandSpec, *, policy: IsolationPolicy, workspace: Path) -> ExecutionResult:
        output = Path(command.environment["AUTODEV_BUILD_OUTPUT"]).resolve()
        output.mkdir(parents=True, exist_ok=True)
        def mapped(value: str) -> str:
            path = Path(value)
            if path.is_absolute():
                try: return "/workspace/" + path.resolve().relative_to(workspace).as_posix()
                except ValueError: pass
                try: return "/environment/" + path.resolve().relative_to(output).as_posix()
                except ValueError: pass
            return value
        argv = [mapped(value) for value in command.argv]
        if Path(argv[0]).is_absolute() or argv[0].lower().endswith(("python", "python.exe")):
            argv[0] = "python"
        docker = [self.docker_executable, "run", "--rm", "--read-only",
                  "--network", "none" if policy.network is NetworkPolicy.NONE else "bridge",
                  "--mount", f"type=bind,src={workspace},dst=/workspace,readonly",
                  "--mount", f"type=bind,src={output},dst=/environment",
                  "--workdir", "/workspace", self.image, *argv]
        return ProcessRunner().run(CommandSpec(tuple(docker), command.timeout_seconds, stdin=command.stdin),
                                   policy=IsolationPolicy(authoritative=False, fresh_worktree=False))

    def run(self, command: CommandSpec, *, policy: IsolationPolicy) -> ExecutionResult:
        if policy.network is not NetworkPolicy.NONE:
            raise ValueError("DockerSandboxProvider supports authoritative network=none only")
        workspace = Path(command.cwd or ".").resolve()
        if not workspace.is_dir():
            raise ValueError("sandbox command cwd must be an existing workspace")
        if "AUTODEV_BUILD_OUTPUT" in command.environment:
            return self._run_build(command, policy=policy, workspace=workspace)
        temporary = Path(command.environment.get("TMP", command.environment.get("TEMP", ""))).resolve()
        if not temporary.is_dir():
            raise ValueError("sandbox requires an existing runner-owned temporary directory")
        executable = Path(command.environment.get("AUTODEV_BOUND_EXECUTABLE", "")).resolve()
        implementation = Path(command.environment.get("AUTODEV_BOUND_IMPLEMENTATION", "")).resolve()
        if not executable.is_file() or not implementation.is_dir():
            raise ValueError("sandbox requires runner-bound executable and implementation mounts")
        argv = list(command.argv); argv[0] = "/opt/autodev/bin/sut-executable"
        docker = [
            self.docker_executable, "run", "--rm", "--network", "none", "--read-only",
            "--mount", f"type=bind,src={workspace},dst=/workspace",
            "--mount", f"type=bind,src={temporary},dst=/tmp/autodev",
            "--mount", f"type=bind,src={executable},dst=/opt/autodev/bin/sut-executable,readonly",
            "--mount", f"type=bind,src={implementation},dst=/opt/autodev/sut,readonly",
            "--workdir", "/workspace", "--env", "TMP=/tmp/autodev", "--env", "TEMP=/tmp/autodev", "--env", "TMPDIR=/tmp/autodev",
            "--env", "PYTHONPATH=/opt/autodev/sut",
        ]
        for name, value in sorted(command.environment.items()):
            if name not in {"TMP", "TEMP", "TMPDIR", "PYTHONPATH", "AUTODEV_BOUND_EXECUTABLE", "AUTODEV_BOUND_IMPLEMENTATION"}:
                docker.extend(("--env", f"{name}={value}"))
        docker.extend((self.image, *argv))
        return ProcessRunner().run(CommandSpec(tuple(docker), command.timeout_seconds, stdin=command.stdin),
                                   policy=IsolationPolicy(authoritative=False, fresh_worktree=False))
