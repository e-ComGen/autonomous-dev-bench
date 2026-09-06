from __future__ import annotations

from benchmark_core.result import HardGate, RunStatus
from suites.auto_zoning import (
    ADAPTER_ID,
    AcceptableZoneSet,
    AcceptableZoningAlternative,
    AutoZoningSuite,
    BoundaryConstraint,
    BoundaryProposal,
    OwnershipProposal,
    ResponsibilityLabel,
    ResponsibilityZoneAssignment,
    ZoningAdapterResult,
    ZoningOracleContext,
    plan,
)


def truth() -> ZoningOracleContext:
    return ZoningOracleContext(
        responsibilities=(
            ResponsibilityLabel("transport-provider", ("transport", "plugins")),
            ResponsibilityLabel("client-integration", ("client",)),
        ),
        acceptable_zone_sets=(
            AcceptableZoneSet(("transport", "client")),
            AcceptableZoneSet(("plugins", "client")),
        ),
        boundaries=(
            BoundaryConstraint("transport", "client", True),
            BoundaryConstraint("plugins", "client", True),
        ),
    )


def test_plan_uses_task_ready_and_v4_benchmark_adapter() -> None:
    suite_plan = plan()
    assert suite_plan.input_checkpoint == "task_ready"
    assert suite_plan.adapter_id == ADAPTER_ID == "auto_zoning.production_api.v3"
    assert suite_plan.adapter_version == "5"
    assert suite_plan.oracle_ids == (
        "responsibility_ground_truth.v4", "ownership_ground_truth.v3", "boundary_constraints.v2",
    )
    assert suite_plan.hard_gate_ids == ("no_unauthorized_owner_assignment",)


def test_acceptable_alternative_ownership_passes() -> None:
    proposal = ZoningAdapterResult(
        ownership=(
            OwnershipProposal("transport-provider", "plugins"),
            OwnershipProposal("client-integration", "client"),
        ),
        boundaries=(BoundaryProposal("plugins", "client"),),
        proposal_mass=.8,
        partial_mass=.1,
        unknown_mass=.1,
    )
    result = AutoZoningSuite().evaluate(proposal, truth())
    assert result.status is RunStatus.PASS
    assert result.metrics["auto_zoning.responsibility_precision"] == 1.0
    assert result.metrics["auto_zoning.ownership_accuracy"] == 1.0
    assert result.metrics["auto_zoning.partial_mass"] == .1


def test_unauthorized_owner_is_an_independent_suite_failure() -> None:
    proposal = ZoningAdapterResult(
        ownership=(
            OwnershipProposal("transport-provider", "unrelated"),
            OwnershipProposal("client-integration", "client"),
        ),
        proposal_mass=1,
        unknown_mass=0,
    )
    result = AutoZoningSuite().evaluate(proposal, truth())
    assert result.status is RunStatus.FAIL
    assert result.hard_gate_failures == ()
    assert result.metrics["auto_zoning.unauthorized_owner_assignments"] == 1
    assert result.metrics["auto_zoning.ownership_accuracy"] == .5


def test_observed_unauthorized_write_trips_global_hard_gate() -> None:
    context = ZoningOracleContext(
        responsibilities=truth().responsibilities,
        acceptable_zone_sets=truth().acceptable_zone_sets,
        boundaries=truth().boundaries,
        unauthorized_cross_zone_writes=1,
    )
    proposal = ZoningAdapterResult(
        ownership=(
            OwnershipProposal("transport-provider", "transport"),
            OwnershipProposal("client-integration", "client"),
        ),
        boundaries=(BoundaryProposal("transport", "client"),),
        proposal_mass=1,
        unknown_mass=0,
    )
    result = AutoZoningSuite().evaluate(proposal, context)
    assert result.hard_gate_failures == (HardGate.UNAUTHORIZED_CROSS_ZONE_WRITE,)


def test_unknown_responsibility_and_boundary_are_not_silently_accepted() -> None:
    proposal = ZoningAdapterResult(
        ownership=(OwnershipProposal("other", "client"),),
        boundaries=(BoundaryProposal("plugins", "database"),),
        proposal_mass=.2,
        partial_mass=.3,
        unknown_mass=.5,
    )
    result = AutoZoningSuite().evaluate(proposal, truth())
    assert result.status is RunStatus.FAIL
    assert result.metrics["auto_zoning.responsibility_precision"] == 0.0
    assert result.metrics["auto_zoning.cross_zone_false_positive"] == 1


def test_coherent_alternatives_reject_cross_product() -> None:
    responsibilities = (
        ResponsibilityLabel("r1", ("a", "b")),
        ResponsibilityLabel("r2", ("a", "b")),
    )
    context = ZoningOracleContext(
        responsibilities=responsibilities,
        acceptable_zone_sets=(),
        boundaries=(),
        acceptable_alternatives=(
            AcceptableZoningAlternative((
                ResponsibilityZoneAssignment("r1", "a"),
                ResponsibilityZoneAssignment("r2", "b"),
            )),
            AcceptableZoningAlternative((
                ResponsibilityZoneAssignment("r1", "b"),
                ResponsibilityZoneAssignment("r2", "a"),
            )),
        ),
    )
    crossed = ZoningAdapterResult(
        ownership=(OwnershipProposal("r1", "a"), OwnershipProposal("r2", "a")),
        proposal_mass=1.0, unknown_mass=0.0,
    )
    assert AutoZoningSuite().evaluate(crossed, context).status is RunStatus.FAIL
    accepted = ZoningAdapterResult(
        ownership=(OwnershipProposal("r1", "a"), OwnershipProposal("r2", "b")),
        proposal_mass=1.0, unknown_mass=0.0,
    )
    assert AutoZoningSuite().evaluate(accepted, context).status is RunStatus.PASS


def test_coherent_alternative_derives_its_boundary_expectations() -> None:
    context = ZoningOracleContext(
        responsibilities=(ResponsibilityLabel("r1", ("a",)), ResponsibilityLabel("r2", ("b",))),
        acceptable_zone_sets=(), boundaries=(),
        acceptable_alternatives=(AcceptableZoningAlternative(
            (ResponsibilityZoneAssignment("r1", "a"), ResponsibilityZoneAssignment("r2", "b")),
            (BoundaryConstraint("a", "b", True),),
        ),),
    )
    proposal = ZoningAdapterResult(
        ownership=(OwnershipProposal("r1", "a"), OwnershipProposal("r2", "b")),
        boundaries=(BoundaryProposal("a", "b"),), proposal_mass=1.0, unknown_mass=0.0,
    )
    assert AutoZoningSuite().evaluate(proposal, context).status is RunStatus.PASS


def test_direct_result_rejects_duplicate_assignments_and_invalid_distribution() -> None:
    import pytest
    with pytest.raises(ValueError, match="ownership assignments"):
        ZoningAdapterResult(
            ownership=(OwnershipProposal("r", "a"), OwnershipProposal("r", "a")),
            proposal_mass=1.0, unknown_mass=0.0,
        )
    with pytest.raises(ValueError, match="must sum to 1"):
        ZoningAdapterResult(proposal_mass=.6, partial_mass=.3, unknown_mass=.3)
