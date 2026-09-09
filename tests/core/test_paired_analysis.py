from __future__ import annotations

from dataclasses import replace

import pytest

from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_analysis import (
    ANALYSIS_ALPHA,
    ExclusionReason,
    ExperimentWinner,
    IncompletePairedSchedule,
    PairOutcomeAttempt,
    PairScheduleEntry,
    PairedAnalysisError,
    PairedExperimentSchedule,
    analyze_final_paired_binary,
    audit_paired_ledger,
    exact_mcnemar_two_sided,
)


DIGEST_A = Sha256Digest("sha256:" + "a" * 64)
DIGEST_B = Sha256Digest("sha256:" + "b" * 64)
DIGEST_C = Sha256Digest("sha256:" + "c" * 64)
DIGEST_D = Sha256Digest("sha256:" + "d" * 64)


def _schedule(count: int = 6) -> PairedExperimentSchedule:
    return PairedExperimentSchedule(
        design_identity=DIGEST_A,
        entries=tuple(
            PairScheduleEntry(
                pair_id=f"phase3d-task-{index}-r0",
                task_id=f"task-{index}",
                repeat_index=0,
                seed=1000 + index,
            )
            for index in range(count)
        ),
    )


def _included(entry: PairScheduleEntry, *, stock: bool, adcp: bool, attempt_index: int = 0) -> PairOutcomeAttempt:
    return PairOutcomeAttempt(
        pair_id=entry.pair_id,
        task_id=entry.task_id,
        repeat_index=entry.repeat_index,
        seed=entry.seed,
        attempt_index=attempt_index,
        stock_manifest_identity=DIGEST_A,
        adcp_manifest_identity=DIGEST_B,
        stock_resolved=stock,
        adcp_resolved=adcp,
        stock_grader_evidence=DIGEST_C,
        adcp_grader_evidence=DIGEST_D,
    )


def _excluded(entry: PairScheduleEntry, *, reason: ExclusionReason, attempt_index: int = 0) -> PairOutcomeAttempt:
    return PairOutcomeAttempt(
        pair_id=entry.pair_id,
        task_id=entry.task_id,
        repeat_index=entry.repeat_index,
        seed=entry.seed,
        attempt_index=attempt_index,
        stock_manifest_identity=DIGEST_A,
        adcp_manifest_identity=DIGEST_B,
        stock_resolved=None,
        adcp_resolved=None,
        exclusion_reason=reason,
        exclusion_evidence=DIGEST_C,
    )


def test_incomplete_schedule_exposes_only_completeness_audit_and_blocks_final_statistics() -> None:
    schedule = _schedule(3)
    attempts = (_included(schedule.entries[0], stock=False, adcp=True),)

    audit = audit_paired_ledger(schedule, attempts)
    assert audit.complete is False
    assert audit.expected_pairs == 3
    assert audit.completed_pairs == 1
    assert audit.missing_pair_ids == (
        schedule.entries[1].pair_id,
        schedule.entries[2].pair_id,
    )

    with pytest.raises(IncompletePairedSchedule, match="requires all 3 pairs"):
        analyze_final_paired_binary(schedule, attempts)


def test_excluded_attempt_does_not_complete_pair_but_terminal_rerun_does() -> None:
    schedule = _schedule(2)
    first = schedule.entries[0]
    attempts = (
        _excluded(first, reason=ExclusionReason.PRE_DISPATCH_INFRASTRUCTURE_FAILURE, attempt_index=0),
        _included(first, stock=False, adcp=True, attempt_index=1),
        _included(schedule.entries[1], stock=True, adcp=True),
    )

    audit = audit_paired_ledger(schedule, attempts)
    assert audit.complete is True
    assert audit.completed_pairs == 2
    assert audit.excluded_attempts == 1

    report = analyze_final_paired_binary(schedule, attempts)
    assert report.excluded_attempt_count == 1
    assert report.pair_count == 2
    assert report.adcp_only_count == 1
    assert report.both_resolved_count == 1


def test_six_adcp_only_discordant_pairs_cross_precommitted_exact_threshold() -> None:
    schedule = _schedule(6)
    attempts = tuple(_included(entry, stock=False, adcp=True) for entry in schedule.entries)

    report = analyze_final_paired_binary(schedule, attempts)

    assert report.stock_resolved_count == 0
    assert report.adcp_resolved_count == 6
    assert report.stock_only_count == 0
    assert report.adcp_only_count == 6
    assert report.discordant_pair_count == 6
    assert report.stock_resolution_rate == 0.0
    assert report.adcp_resolution_rate == 1.0
    assert report.paired_effect_adcp_minus_stock == 1.0
    assert report.exact_mcnemar_two_sided_p == pytest.approx(0.03125)
    assert report.exact_mcnemar_two_sided_p < ANALYSIS_ALPHA
    assert report.statistically_significant is True
    assert report.winner is ExperimentWinner.ADCP


def test_five_adcp_only_pairs_are_positive_effect_but_inconclusive_at_alpha_point_zero_five() -> None:
    schedule = _schedule(5)
    attempts = tuple(_included(entry, stock=False, adcp=True) for entry in schedule.entries)

    report = analyze_final_paired_binary(schedule, attempts)

    assert report.paired_effect_adcp_minus_stock == 1.0
    assert report.exact_mcnemar_two_sided_p == pytest.approx(0.0625)
    assert report.statistically_significant is False
    assert report.winner is ExperimentWinner.INCONCLUSIVE


def test_stock_winner_rule_is_symmetric() -> None:
    schedule = _schedule(6)
    attempts = tuple(_included(entry, stock=True, adcp=False) for entry in schedule.entries)

    report = analyze_final_paired_binary(schedule, attempts)

    assert report.paired_effect_adcp_minus_stock == -1.0
    assert report.exact_mcnemar_two_sided_p == pytest.approx(0.03125)
    assert report.winner is ExperimentWinner.STOCK


def test_all_ties_have_zero_effect_and_exact_p_one() -> None:
    schedule = _schedule(4)
    outcomes = ((True, True), (False, False), (True, True), (False, False))
    attempts = tuple(
        _included(entry, stock=stock, adcp=adcp)
        for entry, (stock, adcp) in zip(schedule.entries, outcomes, strict=True)
    )

    report = analyze_final_paired_binary(schedule, attempts)

    assert report.discordant_pair_count == 0
    assert report.paired_effect_adcp_minus_stock == 0.0
    assert report.exact_mcnemar_two_sided_p == 1.0
    assert report.winner is ExperimentWinner.INCONCLUSIVE


def test_exact_mcnemar_rejects_negative_counts_and_is_symmetric() -> None:
    assert exact_mcnemar_two_sided(stock_only=2, adcp_only=5) == exact_mcnemar_two_sided(stock_only=5, adcp_only=2)
    with pytest.raises(ValueError, match="stock_only"):
        exact_mcnemar_two_sided(stock_only=-1, adcp_only=2)


def test_pair_outcome_identity_must_match_schedule() -> None:
    schedule = _schedule(1)
    attempt = _included(schedule.entries[0], stock=False, adcp=False)

    with pytest.raises(PairedAnalysisError, match="identity differs from schedule"):
        audit_paired_ledger(schedule, (replace(attempt, seed=attempt.seed + 1),))


def test_multiple_included_attempts_for_same_pair_are_rejected() -> None:
    schedule = _schedule(1)
    entry = schedule.entries[0]
    attempts = (
        _included(entry, stock=False, adcp=False, attempt_index=0),
        _included(entry, stock=True, adcp=True, attempt_index=1),
    )

    with pytest.raises(PairedAnalysisError):
        audit_paired_ledger(schedule, attempts)


def test_attempt_after_included_terminal_outcome_is_rejected() -> None:
    schedule = _schedule(1)
    entry = schedule.entries[0]
    attempts = (
        _included(entry, stock=False, adcp=False, attempt_index=0),
        _excluded(entry, reason=ExclusionReason.EXPERIMENT_ACCOUNTING_UNKNOWN, attempt_index=1),
    )

    with pytest.raises(PairedAnalysisError, match="after an included terminal outcome"):
        audit_paired_ledger(schedule, attempts)


def test_excluded_attempt_requires_evidence_and_included_attempt_requires_both_grader_evidence() -> None:
    entry = _schedule(1).entries[0]

    with pytest.raises(ValueError, match="exclusion evidence"):
        PairOutcomeAttempt(
            pair_id=entry.pair_id,
            task_id=entry.task_id,
            repeat_index=entry.repeat_index,
            seed=entry.seed,
            attempt_index=0,
            stock_manifest_identity=DIGEST_A,
            adcp_manifest_identity=DIGEST_B,
            stock_resolved=None,
            adcp_resolved=None,
            exclusion_reason=ExclusionReason.OFFICIAL_GRADER_INFRASTRUCTURE_FAILURE,
        )

    with pytest.raises(ValueError, match="official grader evidence"):
        PairOutcomeAttempt(
            pair_id=entry.pair_id,
            task_id=entry.task_id,
            repeat_index=entry.repeat_index,
            seed=entry.seed,
            attempt_index=0,
            stock_manifest_identity=DIGEST_A,
            adcp_manifest_identity=DIGEST_B,
            stock_resolved=False,
            adcp_resolved=False,
        )
