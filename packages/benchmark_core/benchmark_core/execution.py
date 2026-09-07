"""Safe subprocess execution with timeouts and process-tree cleanup."""
from __future__ import annotations
from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Mapping, Protocol, Sequence
from .identity import FrozenDict
from .isolation import IsolationCapabilities, IsolationPolicy, IsolationUnavailable, SandboxAttestation, local_process_capabilities, validate_isolation


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    timeout_seconds: float = 300.0
    cwd: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    stdin: str | None = None
    inherit_environment: bool = True

    def __post_init__(self) -> None:
        argv = tuple(self.argv)
        if not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            raise ValueError("argv must be a non-empty sequence of non-empty strings")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(self.inherit_environment) is not bool:
            raise ValueError("inherit_environment must be boolean")
        environment = dict(self.environment)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
            raise ValueError("environment keys and values must be strings")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", FrozenDict(environment))


@dataclass(frozen=True)
class ExecutionResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    wall_time_seconds: float

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.returncode == 0


class SandboxProvider(Protocol):
    """Operator-trusted provider that enforces and attests OS-level confinement."""
    def attest(self) -> SandboxAttestation: ...
    def run(self, command: CommandSpec, *, policy: IsolationPolicy) -> ExecutionResult: ...


class ProcessRunner:
    def __init__(self, *, capabilities: IsolationCapabilities | None = None) -> None:
        self.capabilities = capabilities or local_process_capabilities()

    def run(self, command: CommandSpec | Sequence[str], *, policy: IsolationPolicy | None = None) -> ExecutionResult:
        spec = command if isinstance(command, CommandSpec) else CommandSpec(tuple(command))
        effective = policy or IsolationPolicy(authoritative=False, fresh_worktree=False)
        validate_isolation(effective, self.capabilities)
        if effective.authoritative:
            raise IsolationUnavailable("plain ProcessRunner cannot provide authoritative OS confinement; configure an attested SandboxProvider")
        env = os.environ.copy() if spec.inherit_environment else {}
        env.update(spec.environment)
        kwargs: dict[str, object] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        started = time.monotonic()
        process = subprocess.Popen(list(spec.argv), cwd=spec.cwd, env=env, stdin=subprocess.PIPE if spec.stdin is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace", shell=False, **kwargs)
        try:
            stdout, stderr = process.communicate(spec.stdin, timeout=spec.timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_tree(process)
            stdout, stderr = process.communicate()
        return ExecutionResult(spec.argv, process.returncode, stdout, stderr, timed_out, time.monotonic() - started)

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
