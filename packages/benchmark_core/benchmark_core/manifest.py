"""Exact versioned JSON manifest loaders; unknown fields are rejected."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .experiment import SuitePlan
from .project import (
    BaselineSpec, BootstrapSpec, ClassificationSpec, CommandSpec, CorpusSpec,
    InstallSpec, LegalSpec, PlatformSpec, ProjectSource, ProjectSpec, SecuritySpec,
)
from .scenario import CheckpointSpec, FaultApplication, MutationApplication, ScenarioExecution, ScenarioSpec
from .task import ArchitectureConstraints, CrossZoneContract, ExpectedScope, FunctionalOracleRef, TaskSpec


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def load_json(path: str | Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    return value


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{path} must be an integer >= {minimum}")
    return value


def _strings(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{path} must be an array of non-empty strings")
    return tuple(value)


def _exact(value: Mapping[str, Any], path: str, required: set[str], optional: set[str] = set()) -> None:
    keys = set(value)
    missing, unknown = required - keys, keys - required - optional
    if missing or unknown:
        raise ValueError(f"{path} schema mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}")


def project_from_mapping(value: Mapping[str, Any]) -> ProjectSpec:
    _exact(value, "project", {"benchmark_spec_version", "project_id", "source", "legal", "platforms", "bootstrap", "baseline", "classification", "security", "corpus"})
    source = _object(value["source"], "source"); _exact(source, "source", {"repository", "commit_sha", "source_tree_digest"})
    legal = _object(value["legal"], "legal"); _exact(legal, "legal", {"license_spdx", "license_file", "license_file_digest"})
    platforms = _object(value["platforms"], "platforms"); _exact(platforms, "platforms", {"operating_systems", "python"})
    bootstrap = _object(value["bootstrap"], "bootstrap"); _exact(bootstrap, "bootstrap", {"adapter_id", "dependency_spec_digests", "dependency_spec_paths", "install"}, {"extras"})
    install = _object(bootstrap["install"], "bootstrap.install"); _exact(install, "bootstrap.install", {"command_id", "argv"}, {"timeout_seconds", "environment"})
    baseline = _object(value["baseline"], "baseline"); _exact(baseline, "baseline", {"commands", "required_status", "baseline_health_revision"})
    if not isinstance(baseline["commands"], list):
        raise ValueError("baseline.commands must be an array")
    commands = []
    for index, raw in enumerate(baseline["commands"]):
        item = _object(raw, f"baseline.commands[{index}]"); _exact(item, f"baseline.commands[{index}]", {"id", "argv", "timeout_seconds"}, {"environment"})
        commands.append(CommandSpec(_string(item["id"], f"baseline.commands[{index}].id"), _strings(item["argv"], f"baseline.commands[{index}].argv"), _integer(item["timeout_seconds"], f"baseline.commands[{index}].timeout_seconds", minimum=1), _object(item.get("environment", {}), f"baseline.commands[{index}].environment")))
    classification = _object(value["classification"], "classification"); _exact(classification, "classification", {"scale", "domain", "architecture_features", "capabilities_exercised"}, {"dynamic_features"})
    security = _object(value["security"], "security"); _exact(security, "security", {"build_network_policy", "execution_network_policy"})
    corpus = _object(value["corpus"], "corpus"); _exact(corpus, "corpus", {"release", "partition"})
    return ProjectSpec(
        project_id=_string(value["project_id"], "project_id"), spec_version=_string(value["benchmark_spec_version"], "benchmark_spec_version"),
        source=ProjectSource(_string(source["repository"], "source.repository"), _string(source["commit_sha"], "source.commit_sha"), _string(source["source_tree_digest"], "source.source_tree_digest")),
        legal=LegalSpec(_string(legal["license_spdx"], "legal.license_spdx"), _string(legal["license_file_digest"], "legal.license_file_digest"), _string(legal["license_file"], "legal.license_file")),
        platforms=PlatformSpec(_strings(platforms["operating_systems"], "platforms.operating_systems"), _strings(platforms["python"], "platforms.python")),
        bootstrap=BootstrapSpec(
            _string(bootstrap["adapter_id"], "bootstrap.adapter_id"), _strings(bootstrap["dependency_spec_digests"], "bootstrap.dependency_spec_digests"),
            _strings(bootstrap["dependency_spec_paths"], "bootstrap.dependency_spec_paths"), _strings(bootstrap.get("extras", []), "bootstrap.extras"),
            InstallSpec(_string(install["command_id"], "bootstrap.install.command_id"), _strings(install["argv"], "bootstrap.install.argv"), _integer(install.get("timeout_seconds", 1200), "bootstrap.install.timeout_seconds", minimum=1), _object(install.get("environment", {}), "bootstrap.install.environment")),
        ),
        baseline=BaselineSpec(tuple(commands), _string(baseline["required_status"], "baseline.required_status"), _string(baseline["baseline_health_revision"], "baseline.baseline_health_revision")),
        classification=ClassificationSpec(_string(classification["scale"], "classification.scale"), _strings(classification["domain"], "classification.domain"), _strings(classification["architecture_features"], "classification.architecture_features"), _strings(classification.get("dynamic_features", []), "classification.dynamic_features"), _strings(classification["capabilities_exercised"], "classification.capabilities_exercised")),
        security=SecuritySpec(_string(security["build_network_policy"], "security.build_network_policy"), _string(security["execution_network_policy"], "security.execution_network_policy")),
        corpus=CorpusSpec(_string(corpus["release"], "corpus.release"), _string(corpus["partition"], "corpus.partition")),
    )


def task_from_mapping(value: Mapping[str, Any]) -> TaskSpec:
    _exact(value, "task", {"task_id", "task_version", "project_id", "baseline_checkpoint", "user_request", "expected_scope", "cross_zone_contracts", "functional_oracle_ref", "architecture_constraints"})
    scope = _object(value["expected_scope"], "expected_scope"); _exact(scope, "expected_scope", {"affected_domains", "candidate_zones"})
    ref = _object(value["functional_oracle_ref"], "functional_oracle_ref"); _exact(ref, "functional_oracle_ref", {"oracle_id", "version"})
    constraints = _object(value["architecture_constraints"], "architecture_constraints"); _exact(constraints, "architecture_constraints", {"acceptable_families", "forbidden"})
    if not isinstance(value["cross_zone_contracts"], list):
        raise ValueError("cross_zone_contracts must be an array")
    contracts = []
    for index, raw in enumerate(value["cross_zone_contracts"]):
        item = _object(raw, f"cross_zone_contracts[{index}]"); _exact(item, f"cross_zone_contracts[{index}]", {"contract_id", "producer_zone", "consumer_zone"})
        contracts.append(CrossZoneContract(item["contract_id"], item["producer_zone"], item["consumer_zone"]))
    return TaskSpec(
        _string(value["task_id"], "task_id"), _string(value["task_version"], "task_version"), _string(value["project_id"], "project_id"), _string(value["baseline_checkpoint"], "baseline_checkpoint"), _string(value["user_request"], "user_request"),
        ExpectedScope(_strings(scope["affected_domains"], "expected_scope.affected_domains"), _strings(scope["candidate_zones"], "expected_scope.candidate_zones")), tuple(contracts),
        FunctionalOracleRef(_string(ref["oracle_id"], "functional_oracle_ref.oracle_id"), _string(ref["version"], "functional_oracle_ref.version")),
        ArchitectureConstraints(_strings(constraints["acceptable_families"], "architecture_constraints.acceptable_families"), _strings(constraints["forbidden"], "architecture_constraints.forbidden")),
    )


def scenario_from_mapping(value: Mapping[str, Any]) -> ScenarioSpec:
    _exact(value, "scenario", {"scenario_id", "spec_version", "project_id", "task_id", "input_checkpoint", "checkpoints", "mutations", "faults", "execution", "suites", "metadata"})
    for field_name in ("checkpoints", "mutations", "faults", "suites"):
        if not isinstance(value[field_name], list):
            raise ValueError(f"{field_name} must be an array")
    if not isinstance(value["metadata"], Mapping):
        raise ValueError("metadata must be an object")
    checkpoints = []
    bindings: dict[str, tuple[str, str]] = {}
    for index, raw in enumerate(value["checkpoints"]):
        item = _object(raw, f"checkpoints[{index}]"); _exact(item, f"checkpoints[{index}]", {"checkpoint_id", "parent", "overlays"}, {"description"})
        parent = item["parent"]
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"checkpoints[{index}].parent must be a string or null")
        depends = (parent,) if parent else ()
        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"checkpoints[{index}].description must be a string")
        checkpoint = CheckpointSpec(_string(item["checkpoint_id"], f"checkpoints[{index}].checkpoint_id"), depends, description, _strings(item["overlays"], f"checkpoints[{index}].overlays"))
        checkpoints.append(checkpoint)
        for overlay in item["overlays"]:
            if isinstance(overlay, str) and overlay.startswith("mutation:") and item["parent"]:
                bindings[overlay.split(":", 1)[1]] = (item["parent"], item["checkpoint_id"])
    mutations = []
    for index, raw in enumerate(value["mutations"]):
        item = _object(raw, f"mutations[{index}]"); _exact(item, f"mutations[{index}]", {"mutation_id", "seed"}, {"input_checkpoint", "output_checkpoint", "parameters"})
        pair = (item.get("input_checkpoint"), item.get("output_checkpoint"))
        if None in pair:
            try: pair = bindings[item["mutation_id"]]
            except KeyError as exc: raise ValueError(f"cannot bind mutation {item['mutation_id']!r} to checkpoints") from exc
        mutations.append(MutationApplication(_string(item["mutation_id"], f"mutations[{index}].mutation_id"), _string(pair[0], f"mutations[{index}].input_checkpoint"), _string(pair[1], f"mutations[{index}].output_checkpoint"), _integer(item["seed"], f"mutations[{index}].seed"), _object(item.get("parameters", {}), f"mutations[{index}].parameters")))
    faults = []
    for index, raw in enumerate(value["faults"]):
        item = _object(raw, f"faults[{index}]"); _exact(item, f"faults[{index}]", {"fault_id", "checkpoint"}, {"parameters"})
        faults.append(FaultApplication(_string(item["fault_id"], f"faults[{index}].fault_id"), _string(item["checkpoint"], f"faults[{index}].checkpoint"), _object(item.get("parameters", {}), f"faults[{index}].parameters")))
    execution = _object(value["execution"], "execution"); _exact(execution, "execution", {"mode", "timeout_seconds", "network"})
    return ScenarioSpec(
        _string(value["scenario_id"], "scenario_id"), _string(value["spec_version"], "spec_version"), _string(value["project_id"], "project_id"),
        _string(value["task_id"], "task_id"), tuple(checkpoints), _string(value["input_checkpoint"], "input_checkpoint"),
        tuple(mutations), tuple(faults), ScenarioExecution(_string(execution["mode"], "execution.mode"), _integer(execution["timeout_seconds"], "execution.timeout_seconds", minimum=1), {"network": _string(execution["network"], "execution.network")}),
        _strings(value["suites"], "suites"), value["metadata"],
    )


def suite_from_mapping(value: Mapping[str, Any]) -> SuitePlan:
    _exact(value, "suite", {"suite_id", "suite_version", "input_checkpoint", "system_adapter", "adapter_version", "policy_version", "acceptance_version", "required_observations", "required_oracles", "suite_hard_gates", "global_hard_gates", "metrics", "labels_ref"})
    return SuitePlan(
        _string(value["suite_id"], "suite_id"), _string(value["suite_version"], "suite_version"), _string(value["input_checkpoint"], "input_checkpoint"), _string(value["system_adapter"], "system_adapter"),
        _strings(value["required_oracles"], "required_oracles"), _strings(value["required_observations"], "required_observations"), _strings(value["suite_hard_gates"], "suite_hard_gates"),
        _string(value["adapter_version"], "adapter_version"), _string(value["policy_version"], "policy_version"), _string(value["acceptance_version"], "acceptance_version"), _strings(value["global_hard_gates"], "global_hard_gates"),
        _strings(value["metrics"], "metrics"), _string(value["labels_ref"], "labels_ref"),
    )


def load_project(path: str | Path) -> ProjectSpec: return project_from_mapping(load_json(path))
def load_task(path: str | Path) -> TaskSpec: return task_from_mapping(load_json(path))
def load_scenario(path: str | Path) -> ScenarioSpec: return scenario_from_mapping(load_json(path))
def load_suite(path: str | Path) -> SuitePlan: return suite_from_mapping(load_json(path))
