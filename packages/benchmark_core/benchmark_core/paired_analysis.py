"""Precommitted paired binary analysis for the first Stock-vs-ADCP experiment.

The final primary analysis is intentionally unavailable until the full locked
schedule has exactly one included outcome per pair. Infrastructure/accounting
exclusions remain in the ledger as attempts but never count as completed pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable, Mapping

from .experiment_preregistration import ExperimentDesignSnapshot
from .identity import CanonicalModel, Sha256Digest, require_identifier


ANALYSIS_TEST = "exact_mcnemar_two_sided"
ANALYSIS_EFFECT_DIRECTION = "adcp_minus_stock"
ANALYSIS_NULL_DISCORDANT_WIN_PROBABILITY = 0.5
ANALYSIS_ALPHA = 0.05


class PairedAnalysisError(ValueError):
    """Outcome evidence violates the preregistered paired-analysis contract."""


class IncompletePairedSchedule(RuntimeError):
    """Final outcome statistics were requested before every pair completed."""


class ExclusionReason(str, Enum):
    PRE_DISPATCH_INFRASTRUCTURE_FAILURE = "pre_dispatch_infrastructure_failure"
    OFFICIAL_GRADER_INFRASTRUCTURE_FAILURE = "official_grader_infrastructure_failure"
    EXPERIMENT_ACCOUNTING_UNKNOWN = "experiment_accounting_unknown"


class ExperimentWinner(str, Enum):
    ADCP = "ADCP"
    STOCK = "STOCK"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class PairScheduleEntry(CanonicalModel):
    pair_id: str
    task_id: str
    repeat_index: int
    seed: int

    def __post_init__(self) -> None:
        require_identifier(self.pair_id, "pair_id")
        require_identifier(self.task_id, "task_id")
        for name in ("repeat_index", "seed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class PairedExperimentSchedule(CanonicalModel):
    design_identity: Sha256Digest
    entries: tuple[PairScheduleEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.design_identity, Sha256Digest):
            object.__setattr__(self, "design_identity", Sha256Digest(str(self.design_identity)))
        entries = tuple(self.entries)
        if not entries:
            raise ValueError("paired schedule must contain at least one pair")
        if any(not isinstance(item, PairScheduleEntry) for item in entries):
            raise TypeError("schedule entries must be PairScheduleEntry values")
        if len({item.pair_id for item in entries}) != len(entries):
            raise ValueError("paired schedule contains duplicate pair_id")
        if len({(item.task_id, item.repeat_index) for item in entries}) != len(entries):
            raise ValueError("paired schedule contains duplicate task/repeat identity")
        object.__setattr__(self, "entries", entries)

    @classmethod
    def from_design(cls, design: ExperimentDesignSnapshot) -> "PairedExperimentSchedule":
        if not isinstance(design, ExperimentDesignSnapshot):
            raise TypeError("design must be ExperimentDesignSnapshot")
        if not design.design_paid_ready or design.repeat_count_per_task is None:
            raise PairedAnalysisError("paired schedule requires a locked paid-ready experiment design")
        entries = tuple(
            PairScheduleEntry(
                pair_id=design.expected_pair_id(task_id, repeat_index),
                task_id=task_id,
                repeat_index=repeat_index,
                seed=design.expected_seed(task_id, repeat_index),
            )
            for task_id in design.task_ids
            for repeat_index in range(design.repeat_count_per_task)
        )
        if design.required_completed_pairs != len(entries):
            raise PairedAnalysisError("locked stopping pair count differs from generated schedule")
        return cls(design_identity=design.plan_digest, entries=entries)

    @property
    def by_pair_id(self) -> Mapping[str, PairScheduleEntry]:
        return {item.pair_id: item for item in self.entries}


@dataclass(frozen=True, slots=True)
class PairOutcomeAttempt(CanonicalModel):
    pair_id: str
    task_id: str
    repeat_index: int
    seed: int
    attempt_index: int
    stock_manifest_identity: Sha256Digest
    adcp_manifest_identity: Sha256Digest
    stock_resolved: bool | None
    adcp_resolved: bool | None
    stock_grader_evidence: Sha256Digest | None = None
    adcp_grader_evidence: Sha256Digest | None = None
    exclusion_reason: ExclusionReason | None = None
    exclusion_evidence: Sha256Digest | None = None

    def __post_init__(self) -> None:
        require_identifier(self.pair_id, "pair_id")
        require_identifier(self.task_id, "task_id")
        for name in ("repeat_index", "seed", "attempt_index"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("stock_manifest_identity", "adcp_manifest_identity"):
            value = getattr(self, name)
            if not isinstance(value, Sha256Digest):
                object.__setattr__(self, name, Sha256Digest(str(value)))
        for name in ("stock_grader_evidence", "adcp_grader_evidence", "exclusion_evidence"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Sha256Digest):
                object.__setattr__(self, name, Sha256Digest(str(value)))
        if self.exclusion_reason is not None and not isinstance(self.exclusion_reason, ExclusionReason):
            object.__setattr__(self, "exclusion_reason", ExclusionReason(self.exclusion_reason))

        if self.exclusion_reason is None:
            if not isinstance(self.stock_resolved, bool) or not isinstance(self.adcp_resolved, bool):
                raise ValueError("included pair attempt requires boolean outcomes for both arms")
            if self.stock_grader_evidence is None or self.adcp_grader_evidence is None:
                raise ValueError("included pair attempt requires official grader evidence for both arms")
            if self.exclusion_evidence is not None:
                raise ValueError("included pair attempt cannot carry exclusion evidence")
        else:
            if self.exclusion_evidence is None:
                raise ValueError("excluded pair attempt requires exclusion evidence")

    @property
    def included(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True, slots=True)
class PairedLedgerAudit(CanonicalModel):
    schedule_identity: Sha256Digest
    expected_pairs: int
    completed_pairs: int
    excluded_attempts: int
    missing_pair_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.completed_pairs == self.expected_pairs and not self.missing_pair_ids


@dataclass(frozen=True, slots=True)
class PairOutcomeSummary(CanonicalModel):
    pair_id: str
    task_id: str
    repeat_index: int
    stock_resolved: bool
    adcp_resolved: bool
    paired_difference: int


@dataclass(frozen=True, slots=True)
class PairedBinaryAnalysisReport(CanonicalModel):
    schedule_identity: Sha256Digest
    pair_count: int
    stock_resolved_count: int
    adcp_resolved_count: int
    both_resolved_count: int
    neither_resolved_count: int
    stock_only_count: int
    adcp_only_count: int
    discordant_pair_count: int
    stock_resolution_rate: float
    adcp_resolution_rate: float
    paired_effect_adcp_minus_stock: float
    exact_mcnemar_two_sided_p: float
    alpha: float
    statistically_significant: bool
    winner: ExperimentWinner
    excluded_attempt_count: int
    pair_outcomes: tuple[PairOutcomeSummary, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.schedule_identity, Sha256Digest):
            object.__setattr__(self, "schedule_identity", Sha256Digest(str(self.schedule_identity)))
        if not isinstance(self.winner, ExperimentWinner):
            object.__setattr__(self, "winner", ExperimentWinner(self.winner))
        object.__setattr__(self, "pair_outcomes", tuple(self.pair_outcomes))


def audit_paired_ledger(
    schedule: PairedExperimentSchedule,
    attempts: Iterable[PairOutcomeAttempt],
) -> PairedLedgerAudit:
    """Audit completion without exposing interim treatment-effect statistics."""
    grouped = _validate_and_group(schedule, attempts)
    completed: list[str] = []
    excluded_attempts = 0
    for entry in schedule.entries:
        pair_attempts = grouped.get(entry.pair_id, ())
        included = [item for item in pair_attempts if item.included]
        excluded_attempts += sum(not item.included for item in pair_attempts)
        if len(included) > 1:
            raise PairedAnalysisError(f"pair {entry.pair_id} has multiple included attempts")
        if included:
            completed.append(entry.pair_id)
    missing = tuple(entry.pair_id for entry in schedule.entries if entry.pair_id not in set(completed))
    return PairedLedgerAudit(
        schedule_identity=schedule.content_digest,
        expected_pairs=len(schedule.entries),
        completed_pairs=len(completed),
        excluded_attempts=excluded_attempts,
        missing_pair_ids=missing,
    )


def analyze_final_paired_binary(
    schedule: PairedExperimentSchedule,
    attempts: Iterable[PairOutcomeAttempt],
) -> PairedBinaryAnalysisReport:
    """Compute the preregistered primary analysis only for a complete schedule."""
    attempt_values = tuple(attempts)
    audit = audit_paired_ledger(schedule, attempt_values)
    if not audit.complete:
        raise IncompletePairedSchedule(
            f"final paired analysis requires all {audit.expected_pairs} pairs; completed={audit.completed_pairs}"
        )
    grouped = _validate_and_group(schedule, attempt_values)

    summaries: list[PairOutcomeSummary] = []
    stock_resolved = 0
    adcp_resolved = 0
    both = 0
    neither = 0
    stock_only = 0
    adcp_only = 0

    for entry in schedule.entries:
        included = [item for item in grouped[entry.pair_id] if item.included]
        if len(included) != 1:
            raise PairedAnalysisError(f"pair {entry.pair_id} does not have exactly one included outcome")
        item = included[0]
        assert isinstance(item.stock_resolved, bool)
        assert isinstance(item.adcp_resolved, bool)
        stock_resolved += int(item.stock_resolved)
        adcp_resolved += int(item.adcp_resolved)
        if item.stock_resolved and item.adcp_resolved:
            both += 1
        elif not item.stock_resolved and not item.adcp_resolved:
            neither += 1
        elif item.stock_resolved:
            stock_only += 1
        else:
            adcp_only += 1
        summaries.append(
            PairOutcomeSummary(
                pair_id=item.pair_id,
                task_id=item.task_id,
                repeat_index=item.repeat_index,
                stock_resolved=item.stock_resolved,
                adcp_resolved=item.adcp_resolved,
                paired_difference=int(item.adcp_resolved) - int(item.stock_resolved),
            )
        )

    pair_count = len(schedule.entries)
    p_value = exact_mcnemar_two_sided(stock_only=stock_only, adcp_only=adcp_only)
    effect = (adcp_resolved - stock_resolved) / pair_count
    significant = p_value < ANALYSIS_ALPHA
    if significant and effect > 0:
        winner = ExperimentWinner.ADCP
    elif significant and effect < 0:
        winner = ExperimentWinner.STOCK
    else:
        winner = ExperimentWinner.INCONCLUSIVE

    return PairedBinaryAnalysisReport(
        schedule_identity=schedule.content_digest,
        pair_count=pair_count,
        stock_resolved_count=stock_resolved,
        adcp_resolved_count=adcp_resolved,
        both_resolved_count=both,
        neither_resolved_count=neither,
        stock_only_count=stock_only,
        adcp_only_count=adcp_only,
        discordant_pair_count=stock_only + adcp_only,
        stock_resolution_rate=stock_resolved / pair_count,
        adcp_resolution_rate=adcp_resolved / pair_count,
        paired_effect_adcp_minus_stock=effect,
        exact_mcnemar_two_sided_p=p_value,
        alpha=ANALYSIS_ALPHA,
        statistically_significant=significant,
        winner=winner,
        excluded_attempt_count=audit.excluded_attempts,
        pair_outcomes=tuple(summaries),
    )


def exact_mcnemar_two_sided(*, stock_only: int, adcp_only: int) -> float:
    """Two-sided exact McNemar/binomial test under discordant win p=0.5."""
    for name, value in (("stock_only", stock_only), ("adcp_only", adcp_only)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    discordant = stock_only + adcp_only
    if discordant == 0:
        return 1.0
    tail_end = min(stock_only, adcp_only)
    tail_numerator = sum(math.comb(discordant, i) for i in range(tail_end + 1))
    one_sided_tail = tail_numerator / (2**discordant)
    return min(1.0, 2.0 * one_sided_tail)


def _validate_and_group(
    schedule: PairedExperimentSchedule,
    attempts: Iterable[PairOutcomeAttempt],
) -> dict[str, tuple[PairOutcomeAttempt, ...]]:
    expected = schedule.by_pair_id
    grouped: dict[str, list[PairOutcomeAttempt]] = {}
    seen_attempts: set[tuple[str, int]] = set()
    for item in attempts:
        if not isinstance(item, PairOutcomeAttempt):
            raise TypeError("attempts must contain PairOutcomeAttempt values")
        entry = expected.get(item.pair_id)
        if entry is None:
            raise PairedAnalysisError(f"outcome references pair outside schedule: {item.pair_id}")
        if (item.task_id, item.repeat_index, item.seed) != (entry.task_id, entry.repeat_index, entry.seed):
            raise PairedAnalysisError(f"outcome identity differs from schedule for pair {item.pair_id}")
        attempt_key = (item.pair_id, item.attempt_index)
        if attempt_key in seen_attempts:
            raise PairedAnalysisError(f"duplicate pair attempt identity: {item.pair_id}/{item.attempt_index}")
        seen_attempts.add(attempt_key)
        grouped.setdefault(item.pair_id, []).append(item)

    normalized: dict[str, tuple[PairOutcomeAttempt, ...]] = {}
    for pair_id, values in grouped.items():
        ordered = tuple(sorted(values, key=lambda item: item.attempt_index))
        expected_indices = tuple(range(len(ordered)))
        observed_indices = tuple(item.attempt_index for item in ordered)
        if observed_indices != expected_indices:
            raise PairedAnalysisError(f"pair {pair_id} attempt indices must be contiguous from zero")
        included_positions = [index for index, item in enumerate(ordered) if item.included]
        if included_positions and included_positions[-1] != len(ordered) - 1:
            raise PairedAnalysisError(f"pair {pair_id} has attempts after an included terminal outcome")
        normalized[pair_id] = ordered
    return normalized
