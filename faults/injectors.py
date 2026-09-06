"""Faults injected at process, executor, and protocol boundaries."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
from typing import Callable, Mapping, Sequence

from .base import FaultEvidence, FaultSpec


class _ProcessCrashHandle:
    def __init__(self, process: subprocess.Popen[object], spec: FaultSpec) -> None:
        self.process = process
        self.spec = spec
        self._evidence = FaultEvidence(spec.fault_id, "process", False, {"pid": process.pid})

    @property
    def evidence(self) -> FaultEvidence:
        return self._evidence

    def trigger(self) -> int:
        before = self.process.poll()
        if before is None:
            if os.name == "nt":
                self.process.kill()
            else:
                os.kill(self.process.pid, signal.SIGKILL)
            try:
                code = self.process.wait(timeout=float(self.spec.parameters.get("wait_seconds", 5)))
            except subprocess.TimeoutExpired:
                code = self.process.poll()
        else:
            code = before
        self._evidence = FaultEvidence(self.spec.fault_id, "process", before is None and code is not None,
            {"pid": self.process.pid, "running_before": before is None, "returncode": code})
        return int(code) if code is not None else 0


class ProcessCrashInjector:
    fault_id = "PROCESS_CRASH"

    def arm(self, execution_context: object, fault_spec: FaultSpec) -> _ProcessCrashHandle:
        if fault_spec.fault_id != self.fault_id or not isinstance(execution_context, subprocess.Popen):
            raise ValueError("PROCESS_CRASH requires a matching spec and subprocess.Popen")
        return _ProcessCrashHandle(execution_context, fault_spec)

    def verify_triggered(self, evidence: FaultEvidence, fault_spec: FaultSpec) -> bool:
        return (fault_spec.fault_id == self.fault_id == evidence.fault_id and evidence.boundary == "process"
                and evidence.triggered and evidence.observations.get("running_before") is True
                and isinstance(evidence.observations.get("returncode"), int))


class _ToolTimeoutHandle:
    def __init__(self, context: Mapping[str, object] | None, spec: FaultSpec) -> None:
        self.context = dict(context or {})
        self.spec = spec
        self._evidence = FaultEvidence(spec.fault_id, "tool-executor", False)

    @property
    def evidence(self) -> FaultEvidence:
        return self._evidence

    def trigger(self, command: Sequence[str] | None = None, **kwargs: object) -> subprocess.CompletedProcess[str] | None:
        command = command or self.context.get("command")  # type: ignore[assignment]
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError("TOOL_TIMEOUT requires a command sequence")
        timeout = float(self.spec.parameters.get("timeout_seconds", self.context.get("timeout_seconds", 0.05)))
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        run_kwargs = {"cwd": self.context.get("cwd"), "env": self.context.get("env"), "text": True,
                      "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        run_kwargs.update(kwargs)
        try:
            completed = subprocess.run(command, timeout=timeout, **run_kwargs)  # type: ignore[arg-type]
        except subprocess.TimeoutExpired as exc:
            self._evidence = FaultEvidence(self.spec.fault_id, "tool-executor", True,
                {"timed_out": True, "timeout_seconds": timeout, "command": tuple(command),
                 "stdout_captured": exc.stdout is not None, "stderr_captured": exc.stderr is not None})
            return None
        self._evidence = FaultEvidence(self.spec.fault_id, "tool-executor", False,
            {"timed_out": False, "timeout_seconds": timeout, "command": tuple(command), "returncode": completed.returncode})
        return completed


class ToolTimeoutInjector:
    fault_id = "TOOL_TIMEOUT"

    def arm(self, execution_context: object, fault_spec: FaultSpec) -> _ToolTimeoutHandle:
        if fault_spec.fault_id != self.fault_id:
            raise ValueError("fault spec does not match TOOL_TIMEOUT")
        if execution_context is not None and not isinstance(execution_context, Mapping):
            raise ValueError("TOOL_TIMEOUT context must be a mapping or None")
        return _ToolTimeoutHandle(execution_context, fault_spec)  # type: ignore[arg-type]

    def verify_triggered(self, evidence: FaultEvidence, fault_spec: FaultSpec) -> bool:
        return (fault_spec.fault_id == self.fault_id == evidence.fault_id and evidence.boundary == "tool-executor"
                and evidence.triggered and evidence.observations.get("timed_out") is True
                and float(evidence.observations.get("timeout_seconds", 0)) > 0)


class _DuplicateResultHandle:
    def __init__(self, receiver: Callable[[object], object], spec: FaultSpec) -> None:
        self.receiver = receiver
        self.spec = spec
        self._evidence = FaultEvidence(spec.fault_id, "result-protocol", False)

    @property
    def evidence(self) -> FaultEvidence:
        return self._evidence

    def trigger(self, result: object) -> tuple[object, object]:
        first = self.receiver(result)
        second = self.receiver(result)
        self._evidence = FaultEvidence(self.spec.fault_id, "result-protocol", True,
            {"delivery_count": 2, "same_object": True})
        return first, second


class DuplicateResultInjector:
    fault_id = "DUPLICATE_RESULT"

    def arm(self, execution_context: object, fault_spec: FaultSpec) -> _DuplicateResultHandle:
        if fault_spec.fault_id != self.fault_id or not callable(execution_context):
            raise ValueError("DUPLICATE_RESULT requires a matching spec and result receiver")
        return _DuplicateResultHandle(execution_context, fault_spec)

    def verify_triggered(self, evidence: FaultEvidence, fault_spec: FaultSpec) -> bool:
        return (fault_spec.fault_id == self.fault_id == evidence.fault_id and evidence.boundary == "result-protocol"
                and evidence.triggered and evidence.observations.get("delivery_count") == 2
                and evidence.observations.get("same_object") is True)


PROCESS_CRASH = ProcessCrashInjector()
TOOL_TIMEOUT = ToolTimeoutInjector()
DUPLICATE_RESULT = DuplicateResultInjector()
INJECTORS = {injector.fault_id: injector for injector in (PROCESS_CRASH, TOOL_TIMEOUT, DUPLICATE_RESULT)}
