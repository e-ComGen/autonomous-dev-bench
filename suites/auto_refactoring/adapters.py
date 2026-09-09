"""Benchmark-owned adapters for production Auto-Refactoring interfaces."""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from benchmark_core.execution import CommandSpec, ExecutionResult, ProcessRunner

from .suite import ADAPTER_ID, RefactoringAdapterResult, RefactoringDecision


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).upper().replace("-", "_").replace(" ", "_")


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return ()


def _design_form_details(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Extract the public v0.10 DesignAssessment schema without inventing verdicts."""
    selected_forms: list[str] = []
    opportunity_ids: list[str] = []
    opportunity_kinds: list[str] = []
    opportunity_gates: list[str] = []
    hard_unknowns: list[str] = list(_strings(payload.get("hard_unknowns", ())))
    assessments = payload.get("assessments", ())
    if not isinstance(assessments, Sequence) or isinstance(assessments, (str, bytes)):
        assessments = ()
    for value in assessments:
        assessment = _as_mapping(value)
        opportunity = _as_mapping(assessment.get("opportunity"))
        opportunity_id = opportunity.get("opportunity_id")
        kind = opportunity.get("kind")
        gate = assessment.get("status")
        if opportunity_id is not None:
            opportunity_ids.append(str(opportunity_id))
        if kind is not None:
            opportunity_kinds.append(str(getattr(kind, "value", kind)))
        if gate is not None:
            opportunity_gates.append(str(getattr(gate, "value", gate)))
        hard_unknowns.extend(_strings(opportunity.get("hard_unknowns", ())))
        if assessment.get("current_form_dominated") is True:
            selected = assessment.get("selected_form")
            if selected is not None:
                selected_forms.append(str(getattr(selected, "value", selected)))
    return (
        tuple(selected_forms),
        tuple(opportunity_ids),
        tuple(opportunity_kinds),
        tuple(opportunity_gates),
        tuple(dict.fromkeys(hard_unknowns)),
    )


def normalize_production_result(
    raw: object,
    *,
    stdout: str = "",
    stderr: str = "",
    elapsed: float = 0.0,
    process_status: object = None,
) -> RefactoringAdapterResult:
    """Normalize known fields while retaining every raw production field."""
    payload = _as_mapping(raw)
    gate = _text(payload.get("no_dominated_design_form", ""))
    if gate == "FAIL":
        normalized = RefactoringDecision.REMEDIATE.value
    elif gate == "PASS":
        normalized = RefactoringDecision.KEEP_CURRENT.value
    elif gate == "UNKNOWN":
        normalized = RefactoringDecision.UNKNOWN.value
    else:
        decision = payload.get("decision", payload.get("classification", payload.get("action")))
        candidate = _text(decision or "UNKNOWN")
        if candidate in {"REFACTOR", "CHANGE", "FIX", "APPLY", "REMEDIATE", "APPLY_DESIGN_REFACTOR"}:
            normalized = RefactoringDecision.REMEDIATE.value
        elif candidate in {"KEEP", "SAFE", "KEEP_CURRENT", "NO_CHANGE", "ACCEPT"}:
            normalized = RefactoringDecision.KEEP_CURRENT.value
        else:
            normalized = RefactoringDecision.UNKNOWN.value
    changed = payload.get("changed_paths", payload.get("changed_files", ()))
    if isinstance(changed, str):
        changed = (changed,)
    elif not isinstance(changed, Sequence):
        changed = ()
    certificate = payload.get("certification_claim", payload.get("certificate", payload.get("safe")))
    raw_status = payload.get("status", process_status)
    family = payload.get("remediation_family", payload.get("family", payload.get("selected_design")))
    if isinstance(family, Mapping):
        family = family.get("form", family.get("design_form"))
    selected_forms, opportunity_ids, opportunity_kinds, opportunity_gates, hard_unknowns = (
        _design_form_details(payload)
    )
    remediation_families = tuple(form.lower() for form in selected_forms)
    if family is None and remediation_families:
        family = remediation_families[0]
    controller = payload.get("controller_recommendation")
    controller_recommendation = (
        str(getattr(controller, "value", controller)) if controller is not None else None
    )
    return RefactoringAdapterResult(
        decision=normalized,
        remediation_family=str(family) if family is not None else None,
        design_gate=gate or None,
        controller_recommendation=controller_recommendation,
        remediation_families=remediation_families,
        selected_forms=selected_forms,
        opportunity_ids=opportunity_ids,
        opportunity_kinds=opportunity_kinds,
        opportunity_gates=opportunity_gates,
        hard_unknowns=hard_unknowns,
        changed_paths=tuple(str(path) for path in changed),
        wall_time_seconds=elapsed,
        raw_status=raw_status,
        process_status=process_status if isinstance(process_status, int) else None,
        certification_claim=certificate,
        raw_output=raw,
        stdout=stdout,
        stderr=stderr,
    )


def _is_design_form_analyze(command: Sequence[str]) -> bool:
    lowered = tuple(Path(token).name.lower() for token in command)
    return any(name.startswith("autorefactor-design") for name in lowered) or any(
        token in {"auto_refactoring.design_form", "auto_refactoring.design_form.cli"}
        for token in command
    )


def _complete_design_form_argv(
    command: tuple[str, ...], root: Path, scope: str
) -> tuple[str, ...]:
    values = list(command)
    if "analyze" not in values:
        values.append("analyze")
    analyze_index = values.index("analyze")
    if analyze_index + 1 >= len(values) or values[analyze_index + 1].startswith("-"):
        values.insert(analyze_index + 1, str(root))
    if "--scope" not in values:
        values.extend(("--scope", scope))
    return tuple(values)


def _candidate_snapshot(invocation: object) -> object:
    if isinstance(invocation, Mapping):
        return invocation.get("candidate_snapshot", invocation)
    return getattr(invocation, "candidate_snapshot", invocation)


def _build_command_spec(
    *,
    command_template: tuple[str, ...],
    timeout_seconds: float,
    environment: Mapping[str, str],
    root: Path,
    candidate_snapshot: object,
) -> CommandSpec:
    scope = str(candidate_snapshot.get("affected_scope", ".")) if isinstance(candidate_snapshot, Mapping) else "."
    command = tuple(
        token.replace("{repository}", str(root)).replace("{scope}", scope)
        for token in command_template
    )
    design_analyze = _is_design_form_analyze(command)
    if design_analyze:
        command = _complete_design_form_argv(command, root, scope)
    stdin = None if design_analyze else json.dumps({"candidate_snapshot": candidate_snapshot}, default=str)
    return CommandSpec(
        command,
        timeout_seconds,
        str(root),
        environment=environment,
        stdin=stdin,
    )


def _decode_execution(result: ExecutionResult) -> RefactoringAdapterResult:
    if result.timed_out:
        return normalize_production_result(
            None,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed=result.wall_time_seconds,
            process_status="TIMEOUT",
        )
    try:
        raw: object = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raw = {"unparsed_stdout": result.stdout, "malformed_output": True}
    return normalize_production_result(
        raw,
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed=result.wall_time_seconds,
        process_status=result.returncode,
    )


@dataclass(frozen=True, slots=True)
class ProductionCliAdapter:
    """Invoke the real CLI in a subprocess without trusting its self-verdict.

    Command tokens may contain ``{repository}`` and ``{scope}``; no shell is
    used. The v0.10 ``autorefactor-design analyze`` command receives its
    repository and scope as argv, exactly as the production parser requires.
    Exit status, stdout, stderr, raw JSON, certificate claims, and changed paths
    are all preserved as observations.
    """

    command: tuple[str, ...]
    timeout_seconds: float = 1200.0
    environment: Mapping[str, str] = field(default_factory=dict)
    adapter_id: str = ADAPTER_ID
    adapter_version: str = "2"
    production_system_id: str = "auto-refactoring"
    production_version: str = "0.10.0"
    execution_boundary: str = "subprocess"
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("production CLI command must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        environment = dict(self.environment)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
            raise ValueError("environment must contain string pairs")
        object.__setattr__(self, "environment", environment)

    def _command_spec(self, root: Path, candidate_snapshot: object) -> CommandSpec:
        return _build_command_spec(
            command_template=self.command,
            timeout_seconds=self.timeout_seconds,
            environment=self.environment,
            root=root,
            candidate_snapshot=candidate_snapshot,
        )

    def run(self, repository: str | Path, candidate_snapshot: object) -> RefactoringAdapterResult:
        root = Path(repository).resolve()
        execution = ProcessRunner().run(self._command_spec(root, candidate_snapshot))
        return _decode_execution(execution)

    def validate_system_binding(self, system: object, implementation_path: Path, executable_path: Path) -> bool:
        return (
            getattr(system, "system_id", None) == self.production_system_id
            and getattr(system, "version", None) == self.production_version
            and executable_path.is_file() and _is_design_form_analyze(self.command)
            and (implementation_path / "auto_refactoring/design_form").is_dir()
            and (implementation_path / "auto_refactoring/__init__.py").is_file()
            and f'version = "{self.production_version}"' in (implementation_path.parent / "pyproject.toml").read_text(encoding="utf-8")
        )

    def prepare_command(self, invocation: object, run_context: object) -> CommandSpec:
        root = Path(getattr(run_context, "workspace")).resolve()
        return self._command_spec(root, _candidate_snapshot(invocation))

    @staticmethod
    def parse_execution(result: ExecutionResult):
        return _decode_execution(result).observation()

    def invoke(self, invocation: object, run_context: object):
        """Implement the neutral benchmark SystemAdapter protocol."""
        workspace = getattr(run_context, "workspace", None)
        if workspace is None:
            raise ValueError("run context does not provide an isolated workspace")
        return self.run(workspace, _candidate_snapshot(invocation)).observation()


@dataclass(frozen=True, slots=True)
class DesignFormServiceAdapter:
    """Optional adapter for the exported v0.10 design-form host boundary."""

    factory: Callable[[], object] | None = None
    module_name: str = "auto_refactoring.design_form"
    adapter_id: str = ADAPTER_ID
    adapter_version: str = "2"
    production_system_id: str = "auto-refactoring"
    production_version: str = "0.10.0"
    execution_boundary: str = "in_process"
    read_only: bool = True

    def _service(self) -> object:
        if self.factory is not None:
            return self.factory()
        try:
            module = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise RuntimeError("design-form adapter requires optional auto-refactoring v0.10") from exc
        service_type = getattr(module, "ArchitectureQualityService", None)
        if service_type is None:
            raise RuntimeError("auto_refactoring.design_form lacks ArchitectureQualityService")
        return service_type(assumptions=())

    def run(self, repository: str | Path, candidate_snapshot: object) -> RefactoringAdapterResult:
        service = self._service()
        operation = getattr(service, "analyze_only", None)
        if not callable(operation):
            raise RuntimeError("ArchitectureQualityService lacks analyze_only")
        scope = "."
        wrapped_snapshot = getattr(candidate_snapshot, "candidate_snapshot", candidate_snapshot)
        if isinstance(wrapped_snapshot, Mapping):
            scope = str(wrapped_snapshot.get("affected_scope", "."))
        elif hasattr(wrapped_snapshot, "affected_scope"):
            scope = str(getattr(wrapped_snapshot, "affected_scope"))
        started = time.monotonic()
        raw = operation(Path(repository), scope)
        if hasattr(raw, "to_dict") and callable(raw.to_dict):
            raw = raw.to_dict()
        return normalize_production_result(raw, elapsed=time.monotonic() - started, process_status=0)

    def invoke(self, invocation: object, run_context: object):
        workspace = getattr(run_context, "workspace", None)
        if workspace is None:
            raise ValueError("run context does not provide an isolated workspace")
        return self.run(workspace, invocation).observation()
