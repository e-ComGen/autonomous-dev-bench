"""Hardened benchmark-owned adapters for the optional Auto-Zoning v0.6 API."""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

from benchmark_core.execution import CommandSpec, ExecutionResult
from .suite import ADAPTER_ID, BoundaryProposal, OwnershipProposal, ZoningAdapterResult


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _invocation(value: object) -> tuple[object, str]:
    if isinstance(value, Mapping):
        if "source_snapshot" not in value:
            raise ValueError("invocation.source_snapshot is required")
        return value["source_snapshot"], str(value.get("user_request", ""))
    if hasattr(value, "source_snapshot") and hasattr(value, "user_request"):
        return getattr(value, "source_snapshot"), str(getattr(value, "user_request"))
    raise ValueError("Auto-Zoning invocation must expose source_snapshot and user_request")


def _scope_contract(source_snapshot: object) -> tuple[str, tuple[str, ...]]:
    snapshot = _mapping(source_snapshot)
    fingerprint = snapshot.get("input_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 71 or not fingerprint.startswith("sha256:"):
        raise ValueError("source_snapshot.input_fingerprint must be sha256:<64 lowercase hex>")
    suffix = fingerprint[7:]
    if any(char not in "0123456789abcdef" for char in suffix):
        raise ValueError("source_snapshot.input_fingerprint must be sha256:<64 lowercase hex>")
    if "scope_paths" not in snapshot:
        raise ValueError("invocation.source_snapshot.scope_paths is required")
    raw_paths = snapshot["scope_paths"]
    if not isinstance(raw_paths, (list, tuple)):
        raise ValueError("invocation.source_snapshot.scope_paths must be a list or tuple")
    paths: list[str] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw:
            raise ValueError("scope paths must be non-empty strings")
        path = Path(raw)
        normalized_parts = raw.replace("\\", "/").split("/")
        if raw.startswith(("/", "\\")) or (normalized_parts and ":" in normalized_parts[0]) or path.is_absolute() or ".." in normalized_parts:
            raise ValueError("scope paths must be repository-relative and non-traversing")
        paths.append(path.as_posix())
    if len(set(paths)) != len(paths):
        raise ValueError("scope paths must be unique")
    return fingerprint, tuple(paths)


def _mass(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def _normalized_distribution(payload: Mapping[str, Any]) -> tuple[float, float, float]:
    """Return disjoint proposal/partial/unknown mass summing exactly to one."""
    masses = _mapping(payload.get("mass", {}))
    explicit = any(name in payload for name in ("proposal_mass", "partial_mass", "unknown_mass")) or any(
        name in masses for name in ("proposal", "partial", "unknown")
    )
    if explicit:
        proposal = _mass(payload.get("proposal_mass", masses.get("proposal", 0.0)), "proposal_mass")
        partial = _mass(payload.get("partial_mass", masses.get("partial", 0.0)), "partial_mass")
        unknown_raw = payload.get("unknown_mass", masses.get("unknown"))
        unknown = max(0.0, 1.0 - proposal - partial) if unknown_raw is None else _mass(unknown_raw, "unknown_mass")
        values = (proposal, partial, unknown)
    else:
        coverage = _mapping(payload.get("coverage", {}))
        scope = coverage.get("parse_index_coverage")
        if not isinstance(scope, (int, float)):
            parsed, total = coverage.get("parsed_files"), coverage.get("python_artifacts")
            scope = parsed / total if isinstance(parsed, int) and isinstance(total, int) and total > 0 else 0.0
        attribution = coverage.get("responsibility_attribution_coverage")
        scope = min(1.0, _mass(scope, "parse_index_coverage"))
        attribution = min(1.0, _mass(attribution, "responsibility_attribution_coverage")) if attribution is not None else 0.0
        values = (scope * attribution, scope * (1.0 - attribution), 1.0 - scope)
    total = sum(values)
    if total <= 0.0:
        return 0.0, 0.0, 1.0
    if explicit and abs(total - 1.0) <= 1e-12:
        return values
    proposal, partial, unknown = (value / total for value in values)
    unknown = 1.0 - proposal - partial
    return proposal, partial, unknown


def _derive_v06_boundaries(payload: Mapping[str, Any]) -> tuple[BoundaryProposal, ...]:
    """Derive cross-zone edges from v0.6 facts; v0.6 has no boundary field."""
    entity_zones: dict[str, str] = {}
    for file_record in _records(payload.get("files")):
        for assignment in _records(_mapping(file_record).get("assignments")):
            record = _mapping(assignment)
            entity = record.get("entity_id")
            responsibility = record.get("responsibility_id", record.get("responsibility_key"))
            zone = _mapping(payload.get("responsibility_to_zone", {})).get(responsibility)
            if entity and zone:
                if str(entity) in entity_zones:
                    raise ValueError(f"duplicate entity assignment: {entity}")
                entity_zones[str(entity)] = str(zone)
    pairs: set[tuple[str, str]] = set()
    for fact_value in _records(payload.get("facts")):
        fact = _mapping(fact_value)
        if str(fact.get("status", "")) != "RESOLVED_LOCAL":
            continue
        source = entity_zones.get(str(fact.get("subject", "")))
        if source is None:
            continue
        for target_value in _records(fact.get("targets")):
            target = entity_zones.get(str(target_value))
            if target is not None and target != source:
                pairs.add((source, target))
    return tuple(BoundaryProposal(source, target) for source, target in sorted(pairs))


def normalize_projection(raw: object) -> ZoningAdapterResult:
    """Normalize exact v0.6 proposal output without inventing authority."""
    payload = _mapping(raw)
    owner_source = payload.get(
        "ownership",
        payload.get("assignments", payload.get("responsibility_to_zone", payload.get("responsibilities", ()))),
    )
    ownership: list[OwnershipProposal] = []
    seen_responsibilities: set[str] = set()
    if isinstance(owner_source, Mapping):
        records = ((responsibility, zone, 1.0) for responsibility, zone in owner_source.items())
    else:
        records = (
            (
                _mapping(item).get("responsibility_id", _mapping(item).get("responsibility", _mapping(item).get("name"))),
                _mapping(item).get("zone_id", _mapping(item).get("zone", _mapping(item).get("owner"))),
                _mapping(item).get("mass", _mapping(item).get("confidence", 1.0)),
            )
            for item in _records(owner_source)
        )
    for responsibility, zone, mass in records:
        if responsibility is None or zone in (None, ""):
            continue
        responsibility_id = str(responsibility)
        if responsibility_id in seen_responsibilities:
            raise ValueError(f"duplicate ownership assignment: {responsibility_id}")
        seen_responsibilities.add(responsibility_id)
        ownership.append(OwnershipProposal(responsibility_id, str(zone), _mass(mass, "ownership mass")))

    explicit_boundary_source = payload.get("boundaries", payload.get("cross_zone", payload.get("contracts")))
    boundaries: list[BoundaryProposal] = []
    recognized_v06 = (
        payload.get("schema") in {"autozoning.semantic-analysis/v2", "autozoning.ide-semantic-zoning/v2"}
        or _mapping(payload.get("raw_analysis")).get("schema") == "autozoning.semantic-analysis/v2"
    )
    if explicit_boundary_source is None and recognized_v06:
        boundaries.extend(_derive_v06_boundaries(payload))
    elif explicit_boundary_source is not None:
        seen_pairs: set[tuple[str, str]] = set()
        for item in _records(explicit_boundary_source):
            record = _mapping(item)
            source = record.get("source_zone", record.get("source", record.get("from")))
            target = record.get("target_zone", record.get("target", record.get("to")))
            if source is None or target is None or source == target:
                continue
            pair = (str(source), str(target))
            if pair in seen_pairs:
                raise ValueError(f"duplicate boundary assignment: {pair[0]}->{pair[1]}")
            seen_pairs.add(pair)
            boundaries.append(BoundaryProposal(*pair, _mass(record.get("mass", record.get("confidence", 1.0)), "boundary mass")))

    proposal_mass, partial_mass, unknown_mass = _normalized_distribution(payload)
    known = {
        "ownership", "assignments", "responsibility_to_zone", "responsibilities", "boundaries", "cross_zone", "contracts",
        "proposal_mass", "partial_mass", "unknown_mass", "mass",
    }
    return ZoningAdapterResult(
        tuple(ownership), tuple(boundaries), proposal_mass, partial_mass, unknown_mass,
        raw, {key: value for key, value in payload.items() if key not in known},
    )


class ProductionSemanticAdapter:
    """Diagnostic in-process anti-corruption adapter for Auto-Zoning v0.6."""

    adapter_id = ADAPTER_ID
    adapter_version = "4"
    execution_boundary = "in_process"
    read_only = True

    def __init__(
        self,
        module_name: str = "autozoning.semantic",
        *,
        policy_factory: Callable[[object], object] | None = None,
        seeds: tuple[str, ...] | None = None,
    ) -> None:
        self.module_name = module_name
        self.policy_factory = policy_factory
        self.seeds = None if seeds is None else tuple(seeds)

    def run(self, repository: str | Path, source_snapshot: object, user_request: str,
            *, seeds: Sequence[str] | None = None,
            runner_input_fingerprint: str | None = None) -> ZoningAdapterResult:
        try:
            semantic = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise RuntimeError("Auto-Zoning production adapter requires optional autozoning v0.6") from exc
        frontend_type = getattr(semantic, "RepositorySemanticFrontend", None)
        build_projection = getattr(semantic, "build_projection", None)
        if not callable(build_projection):
            try:
                build_projection = getattr(importlib.import_module(self.module_name + ".projection"), "build_projection")
            except (ImportError, AttributeError) as exc:
                raise RuntimeError("autozoning.semantic.projection lacks build_projection") from exc
        if frontend_type is None:
            raise RuntimeError("autozoning.semantic lacks RepositorySemanticFrontend")

        frontend = frontend_type()
        policy = self.policy_factory(semantic) if self.policy_factory is not None else None
        kwargs: dict[str, object] = {}
        if policy is not None:
            kwargs["policy"] = policy
        selected_seeds = tuple(seeds) if seeds is not None else self.seeds
        if selected_seeds is not None:
            kwargs["seeds"] = list(selected_seeds)
        analysis = frontend.analyze(Path(repository), **kwargs)
        projection = build_projection(analysis)
        if hasattr(projection, "to_dict") and callable(projection.to_dict):
            projection = projection.to_dict()
        if hasattr(analysis, "to_dict") and callable(analysis.to_dict):
            analysis = analysis.to_dict()
        analysis_map = _mapping(analysis)
        projection_map = _mapping(projection)
        combined = dict(projection_map)
        for name, default in (
            ("responsibility_to_zone", {}), ("facts", ()), ("files", ()),
            ("coverage", {}), ("process_status", None), ("semantic_completeness", "PARTIAL"),
        ):
            combined[name] = analysis_map.get(name, combined.get(name, default))
        combined.setdefault("status", analysis_map.get("status"))
        combined["semantic_status"] = analysis_map.get("status")
        combined["raw_analysis"] = analysis
        combined["raw_projection"] = projection
        snapshot_map = _mapping(source_snapshot)
        declared_fingerprint = snapshot_map.get("input_fingerprint")
        combined["runner_input_fingerprint"] = runner_input_fingerprint
        combined["declared_input_fingerprint"] = declared_fingerprint
        combined["snapshot_binding_valid"] = bool(
            runner_input_fingerprint is not None
            and declared_fingerprint is not None
            and str(declared_fingerprint) == str(runner_input_fingerprint)
        )
        combined["source_snapshot"] = source_snapshot
        combined["user_request_recorded"] = bool(user_request)
        return normalize_projection(combined)

    def invoke(self, invocation: object, run_context: object):
        workspace = getattr(run_context, "workspace", None)
        runner_fingerprint = getattr(run_context, "input_fingerprint", None)
        if workspace is None or runner_fingerprint is None:
            raise ValueError("run context lacks workspace or input_fingerprint")
        source_snapshot, user_request = _invocation(invocation)
        _, scope_paths = _scope_contract(source_snapshot)
        result = self.run(
            workspace, source_snapshot, user_request, seeds=scope_paths,
            runner_input_fingerprint=str(runner_fingerprint),
        )
        return result.observation()


@dataclass(frozen=True, slots=True)
class ProductionSemanticSubprocessAdapter:
    """Runner-owned subprocess boundary around the benchmark's v0.6 worker."""

    command: tuple[str, ...] = (sys.executable, "-m", "suites.auto_zoning.worker")
    timeout_seconds: float = 300.0
    environment: Mapping[str, str] = field(default_factory=dict)
    adapter_id: str = ADAPTER_ID
    adapter_version: str = "4"
    production_system_id: str = "auto-zoning"
    production_version: str = "0.6.0"
    execution_boundary: str = "subprocess"
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("worker command must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        environment = dict(self.environment)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
            raise ValueError("environment must contain string pairs")
        object.__setattr__(self, "environment", environment)

    def validate_system_binding(self, system: object, implementation_path: Path, executable_path: Path) -> bool:
        return (
            getattr(system, "system_id", None) == self.production_system_id
            and getattr(system, "version", None) == self.production_version
            and executable_path.is_file()
            and tuple(self.command[1:]) == ("-m", "suites.auto_zoning.worker")
            and (implementation_path / "autozoning/__init__.py").is_file()
            and (implementation_path / "autozoning/semantic").is_dir()
            and f'__version__ = "{self.production_version}"' in (implementation_path / "autozoning/version.py").read_text(encoding="utf-8")
        )

    def prepare_command(self, invocation: object, run_context: object) -> CommandSpec:
        workspace = getattr(run_context, "workspace", None)
        runner_fingerprint = getattr(run_context, "input_fingerprint", None)
        if workspace is None or runner_fingerprint is None:
            raise ValueError("run context lacks workspace or input_fingerprint")
        source_snapshot, user_request = _invocation(invocation)
        declared_fingerprint, scope_paths = _scope_contract(source_snapshot)
        request = {
            "repository": str(workspace),
            "runner_input_fingerprint": str(runner_fingerprint),
            "invocation": {
                "source_snapshot": {"input_fingerprint": declared_fingerprint, "scope_paths": list(scope_paths)},
                "user_request": user_request,
            },
        }
        return CommandSpec(self.command, self.timeout_seconds, str(workspace), environment=self.environment, stdin=json.dumps(request))

    def parse_execution(self, execution: ExecutionResult):
        if execution.timed_out:
            raw: object = {"status": "WORKER_FAILED", "process_status": "TIMEOUT",
                           "stdout": execution.stdout, "stderr": execution.stderr}
        else:
            try:
                raw = json.loads(execution.stdout)
            except json.JSONDecodeError:
                raw = {"status": "WORKER_FAILED", "malformed_output": True,
                       "stdout": execution.stdout, "stderr": execution.stderr}
            if execution.returncode != 0:
                payload = dict(_mapping(raw))
                payload.update({"status": "WORKER_FAILED", "process_status": execution.returncode,
                                "stdout": execution.stdout, "stderr": execution.stderr})
                raw = payload
        return normalize_projection(raw).observation()

    def invoke(self, invocation: object, run_context: object):
        """Non-authoritative convenience path; authoritative runs use runner-owned execution."""
        from benchmark_core.execution import ProcessRunner
        return self.parse_execution(ProcessRunner().run(self.prepare_command(invocation, run_context)))
