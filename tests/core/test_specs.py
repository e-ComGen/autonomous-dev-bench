from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "benchmark_core"))

from benchmark_core.experiment import (
    CoverageVector, EvaluationLevel, ExecutionComposition, ExperimentSpec,
    SuitePlan, SystemUnderTest,
)
from benchmark_core.identity import VersionIdentity
from benchmark_core.project import (
    BaselineSpec, BootstrapSpec, ClassificationSpec, CommandSpec, CorpusSpec,
    LegalSpec, PlatformSpec, ProjectSource, ProjectSpec, SecuritySpec,
)
from benchmark_core.scenario import CheckpointSpec, MutationApplication, ScenarioSpec
from benchmark_core.task import (
    ArchitectureConstraints, AutoZoningView, CoderView, CrossZoneContract,
    ExpectedScope, FunctionalOracleRef, OracleView, TaskAudience, TaskOwnerView,
    TaskSpec,
)

D = "sha256:" + "1" * 64


def make_project() -> ProjectSpec:
    return ProjectSpec(
        project_id="httpx.pinned_001",
        spec_version="1.0",
        source=ProjectSource("encode/httpx", "a" * 40, D),
        legal=LegalSpec("BSD-3-Clause", D),
        platforms=PlatformSpec(("linux", "windows"), ("3.11", "3.12")),
        bootstrap=BootstrapSpec("python-standard-v1", (D,), ("pyproject.toml",), ("tests",)),
        baseline=BaselineSpec((CommandSpec("unit-tests", ("python", "-m", "pytest"), 1200),)),
        classification=ClassificationSpec("medium", ("http-client",), ("async",), ("runtime-dispatch",), ("auto-zoning",)),
        security=SecuritySpec("package-indices-only", "none"),
        corpus=CorpusSpec("2026.1", "validation"),
    )


def make_task() -> TaskSpec:
    return TaskSpec(
        task_id="httpx.add-transport",
        spec_version="v1",
        project_id="httpx.pinned_001",
        baseline_checkpoint="baseline",
        user_request="Add a selectable transport provider.",
        expected_scope=ExpectedScope(("transport",), ("transport-owner", "client")),
        cross_zone_contracts=(CrossZoneContract("transport-contract", "transport-owner", "client"),),
        functional_oracle_ref=FunctionalOracleRef("hidden.httpx.feature", "v1"),
        architecture_constraints=ArchitectureConstraints(("existing-abstraction",), ("global-registry",)),
    )


def test_project_is_content_pinned_and_deeply_immutable() -> None:
    project = make_project()
    assert project.identity.content_digest == project.content_digest
    assert project.source.commit_sha.value == "a" * 40
    with pytest.raises(Exception):
        project.baseline.commands += (project.baseline.commands[0],)  # type: ignore[misc]


def test_task_projections_do_not_leak_hidden_expectations() -> None:
    task = make_task()
    owner = task.project(TaskAudience.TASK_OWNER)
    zoning = task.project("auto_zoning", source_snapshot={"input_fingerprint": D, "scope_paths": ["src/pkg.py"]})
    coder = task.project("coder", approved_zones=("transport-owner",), approved_contracts=("transport-contract",))
    oracle = task.project("oracle")
    assert isinstance(owner, TaskOwnerView)
    assert isinstance(zoning, AutoZoningView)
    assert isinstance(coder, CoderView)
    assert isinstance(oracle, OracleView)
    for public_view in (owner, zoning, coder):
        payload = public_view.to_canonical_json()
        assert "hidden.httpx.feature" not in payload
        assert "acceptable_families" not in payload
        assert "expected_scope" not in payload


def test_projection_requires_stage_context() -> None:
    with pytest.raises(ValueError, match="source_snapshot"):
        make_task().project("auto_zoning")


def test_scenario_validates_checkpoint_dag_and_contains_no_answers() -> None:
    scenario = ScenarioSpec(
        scenario_id="httpx.bad-dispatch",
        spec_version="v1",
        project_id="httpx.pinned_001",
        task_id="httpx.add-transport",
        checkpoints=(CheckpointSpec("baseline"), CheckpointSpec("candidate", ("baseline",), overlays=("mutation:duplicate-dispatch",))),
        input_checkpoint="candidate",
        mutations=(MutationApplication("duplicate-dispatch", "baseline", "candidate", 819283),),
        suite_ids=("auto-refactoring",),
        metadata={"family": "structural"},
    )
    assert scenario.identity.content_digest == scenario.content_digest
    with pytest.raises(ValueError, match="acyclic"):
        ScenarioSpec(
            "cyclic", "v1", "pinned-project", None,
            (CheckpointSpec("a", ("b",)), CheckpointSpec("b", ("a",))), "a",
        )
    with pytest.raises(ValueError, match="answer-free"):
        ScenarioSpec(
            "leaky", "v1", "pinned-project", None, (CheckpointSpec("baseline"),), "baseline",
            metadata={"expected_output": "secret"},
        )


def test_experiment_requires_content_pins_and_one_seed_per_attempt() -> None:
    project = make_project()
    scenario_identity = VersionIdentity("httpx.bad-dispatch", "v1").pinned({"world": "bad-dispatch"})
    task_identity = VersionIdentity("httpx.task", "v1").pinned({"request": "add provider"})
    suite = SuitePlan(
        "auto-refactoring", "v1", "candidate", "normal-api-v1",
        ("independent-safety",), ("changed-tree",), ("false-safe-certificate",),
    )
    experiment = ExperimentSpec(
        "experiment-001", "v1", project.identity, scenario_identity, task_identity,
        SystemUnderTest("autodev", "v5", "b" * 40), (suite,), D,
        EvaluationLevel.L2_LLM_ASSISTED_SUBSYSTEM, ExecutionComposition.SUBSYSTEM,
        attempts=2, seeds=(41, 42), coverage=CoverageVector({"os": "linux", "suite": "auto-refactoring"}),
    )
    assert experiment.cache_key == experiment.content_digest
    with pytest.raises(ValueError, match="content-pinned"):
        ExperimentSpec(
            "bad-experiment", "v1", VersionIdentity("project", "v1"), scenario_identity, task_identity,
            experiment.system, (suite,), D, "L1", "component",
        )
    with pytest.raises(ValueError, match="one non-negative integer"):
        ExperimentSpec(
            "bad-seeds", "v1", project.identity, scenario_identity, task_identity, experiment.system,
            (suite,), D, "L1", "component", attempts=2, seeds=(1,),
        )
