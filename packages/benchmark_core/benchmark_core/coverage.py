"""Deterministic greedy weighted set-cover campaign selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CandidateExperiment:
    experiment_id: str
    covers: frozenset[str]
    estimated_cost: float = 1.0
    risk_weight: float = 0.0
    mandatory: bool = False

    def __post_init__(self) -> None:
        if self.estimated_cost <= 0: raise ValueError("estimated_cost must be positive")


@dataclass(frozen=True)
class CoverageSelection:
    selected: tuple[CandidateExperiment, ...]
    uncovered: frozenset[str]
    total_cost: float


def greedy_select(required: Iterable[str], candidates: Iterable[CandidateExperiment], *, fail_on_uncovered: bool = True) -> CoverageSelection:
    uncovered = set(required); pool = list(candidates); selected: list[CandidateExperiment] = []
    for candidate in sorted((c for c in pool if c.mandatory), key=lambda c: c.experiment_id):
        selected.append(candidate); uncovered -= candidate.covers
    pool = [c for c in pool if c not in selected]
    while uncovered:
        useful = [c for c in pool if c.covers & uncovered]
        if not useful: break
        # Max new weighted coverage per cost, then risk, then stable id.
        best = min(useful, key=lambda c: (-((len(c.covers & uncovered) + c.risk_weight) / c.estimated_cost),
                                          -c.risk_weight, c.estimated_cost, c.experiment_id))
        selected.append(best); uncovered -= best.covers; pool.remove(best)
    if uncovered and fail_on_uncovered: raise ValueError(f"coverage obligations cannot be satisfied: {sorted(uncovered)}")
    return CoverageSelection(tuple(selected), frozenset(uncovered), sum(c.estimated_cost for c in selected))

select_coverage = greedy_select
