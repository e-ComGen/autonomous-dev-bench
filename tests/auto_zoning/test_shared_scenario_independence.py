from __future__ import annotations

from benchmark_core.result import HardGate, RunStatus
from benchmark_core.scenario import CheckpointSpec, MutationApplication, ScenarioSpec
from benchmark_core.task import (
    ArchitectureConstraints,
    CrossZoneContract,
    ExpectedScope,
    FunctionalOracleRef,
    TaskSpec,
)
from suites.auto_refactoring import (
    AutoRefactoringSuite,
    RefactoringAdapterResult,
    RefactoringLabels,
    RefactoringOracleContext,
    plan as refactoring_plan,
)
from suites.auto_zoning import (
    AcceptableZoneSet,
    AutoZoningSuite,
    OwnershipProposal,
    ResponsibilityLabel,
    ZoningAdapterResult,
    ZoningOracleContext,
    plan as zoning_plan,
)


def test_same_scenario_and_task_have_independent_plans_results_and_gates() -> None:
    task = TaskSpec(
        "shared.add-provider", "v1", "project.pinned", "baseline", "Add a provider.",
        ExpectedScope(("transport",), ("transport", "client")),
        (CrossZoneContract("provider-client", "transport", "client"),),
        FunctionalOracleRef("hidden.feature", "v1"),
        ArchitectureConstraints(("strategy", "factory"), ("global-registry",)),
    )
    scenario = ScenarioSpec(
        "shared.provider", "v1", task.project_id, task.task_id,
        (
            CheckpointSpec("baseline"),
            CheckpointSpec("task_ready", ("baseline",)),
            CheckpointSpec("candidate_bad_dispatch", ("task_ready",), overlays=("mutation:duplicate-provider-dispatch",)),
        ),
        "candidate_bad_dispatch",
        (MutationApplication("duplicate-provider-dispatch", "task_ready", "candidate_bad_dispatch", 7),),
        suite_ids=("auto_refactoring", "auto_zoning"),
    )
    assert scenario.task_id == task.task_id
    assert refactoring_plan().input_checkpoint == "candidate_bad_dispatch"
    assert zoning_plan().input_checkpoint == "task_ready"

    ref_result = AutoRefactoringSuite().evaluate(
        RefactoringAdapterResult("KEEP_CURRENT", certification_claim={"safe": True}),
        RefactoringOracleContext(RefactoringLabels(True, True, ("strategy",)), True, True, True),
    )
    zone_result = AutoZoningSuite().evaluate(
        ZoningAdapterResult((OwnershipProposal("transport-provider", "transport"),), proposal_mass=1, unknown_mass=0),
        ZoningOracleContext(
            (ResponsibilityLabel("transport-provider", ("transport",)),),
            (AcceptableZoneSet(("transport",)),),
            (),
        ),
    )
    assert ref_result.status is RunStatus.FAIL
    assert ref_result.hard_gate_failures == (HardGate.FALSE_SAFE_CERTIFICATE,)
    assert zone_result.status is RunStatus.PASS
    assert zone_result.hard_gate_failures == ()
    assert ref_result.oracle_results[0].oracle_id != zone_result.oracle_results[0].oracle_id
