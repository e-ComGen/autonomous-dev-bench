from __future__ import annotations

from benchmark_core.result import HardGate, RunStatus
from suites.auto_refactoring import (
    ADAPTER_ID,
    AutoRefactoringSuite,
    RefactoringAdapterResult,
    RefactoringDecision,
    RefactoringLabels,
    RefactoringOracleContext,
    plan,
)


def context(**overrides: object) -> RefactoringOracleContext:
    values = dict(
        labels=RefactoringLabels(True, True, ("strategy", "factory")),
        functional_preserved=True,
        differential_preserved=True,
        public_api_preserved=True,
    )
    values.update(overrides)
    return RefactoringOracleContext(**values)  # type: ignore[arg-type]


def test_plan_uses_candidate_and_v2_production_adapter() -> None:
    suite_plan = plan()
    assert suite_plan.input_checkpoint == "candidate_bad_dispatch"
    assert suite_plan.adapter_id == ADAPTER_ID == "auto_refactoring.production_api.v2"
    assert suite_plan.oracle_ids == (
        "mutation_presence.independent.v1", "design_opportunity.v3",
        "functional_regression.v2", "differential_behavior.v1", "public_api.v2",
    )
    assert suite_plan.hard_gate_ids == ("no_false_safe", "semantic_preservation")


def test_multiple_remediation_families_are_accepted() -> None:
    suite = AutoRefactoringSuite()
    for family in ("strategy", "factory"):
        result = suite.evaluate(RefactoringAdapterResult(RefactoringDecision.REMEDIATE, family, ("client.py",)), context())
        assert result.status is RunStatus.PASS
        assert result.metrics["auto_refactoring.semantic_preservation"] == 1.0
        assert result.metrics["auto_refactoring.detection_true_positive"] == 1


def test_false_safe_claim_is_independently_rejected() -> None:
    candidate = RefactoringAdapterResult(
        "KEEP_CURRENT", raw_status="SUCCESS", process_status=0,
        certification_claim={"safe": True}, raw_output={"certificate": {"safe": True}},
    )
    result = AutoRefactoringSuite().evaluate(candidate, context())
    assert result.status is RunStatus.FAIL
    assert HardGate.FALSE_SAFE_CERTIFICATE in result.hard_gate_failures
    assert result.metrics["auto_refactoring.false_safe"] == 1


def test_semantic_preservation_is_noncompensable() -> None:
    candidate = RefactoringAdapterResult("REMEDIATE", "strategy", ("client.py",))
    result = AutoRefactoringSuite().evaluate(candidate, context(differential_preserved=False))
    assert HardGate.LOST_REQUIRED_VERIFICATION in result.hard_gate_failures
    assert result.metrics["auto_refactoring.semantic_preservation"] == 0.0


def test_unknown_cannot_pass_keep_current_negative_control() -> None:
    labels = RefactoringLabels(False, False, (), keep_current_expected=True)
    result = AutoRefactoringSuite().evaluate(RefactoringAdapterResult("UNKNOWN"), context(labels=labels))
    assert result.status is RunStatus.FAIL


def test_keep_current_negative_control_passes_and_enum_stays_enum() -> None:
    labels = RefactoringLabels(False, False, (), keep_current_expected=True)
    candidate = RefactoringAdapterResult(RefactoringDecision.KEEP_CURRENT)
    result = AutoRefactoringSuite().evaluate(candidate, context(labels=labels))
    assert candidate.decision is RefactoringDecision.KEEP_CURRENT
    assert result.status is RunStatus.PASS
    assert result.metrics["auto_refactoring.keep_current_accuracy"] == 1.0
    assert result.metrics["auto_refactoring.keep_current_applicable"] == 1
