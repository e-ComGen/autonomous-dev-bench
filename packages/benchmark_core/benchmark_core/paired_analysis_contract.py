"""Single source of truth for the preregistered paired primary analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .identity import CanonicalModel


ANALYSIS_UNIT = "task_repeat_pair"
ANALYSIS_EFFECT_DIRECTION = "adcp_minus_stock"
ANALYSIS_TEST = "exact_mcnemar_two_sided"
ANALYSIS_NULL_DISCORDANT_WIN_PROBABILITY = 0.5
ANALYSIS_ALPHA = 0.05
ANALYSIS_FINAL_REQUIRES_COMPLETE_SCHEDULE = True
ANALYSIS_EXCLUDED_ATTEMPTS_NEVER_COMPLETE_PAIR = True
PRIMARY_ENDPOINT = "official_swebench_v5_resolved"
PRIMARY_ESTIMAND = "paired_difference_in_resolution_rate_adcp_minus_stock"


class PairedAnalysisContractError(ValueError):
    """The experiment plan drifted from the precommitted primary analysis."""


@dataclass(frozen=True, slots=True)
class PairedAnalysisContract(CanonicalModel):
    unit: str = ANALYSIS_UNIT
    effect_direction: str = ANALYSIS_EFFECT_DIRECTION
    inferential_test: str = ANALYSIS_TEST
    null_discordant_win_probability: float = ANALYSIS_NULL_DISCORDANT_WIN_PROBABILITY
    alpha: float = ANALYSIS_ALPHA
    final_analysis_requires_complete_schedule: bool = ANALYSIS_FINAL_REQUIRES_COMPLETE_SCHEDULE
    excluded_attempts_never_count_as_completed_pairs: bool = ANALYSIS_EXCLUDED_ATTEMPTS_NEVER_COMPLETE_PAIR
    primary_endpoint: str = PRIMARY_ENDPOINT
    primary_estimand: str = PRIMARY_ESTIMAND


EXPECTED_ANALYSIS_CONTRACT = PairedAnalysisContract()


def validate_paired_analysis_preregistration(plan: Mapping[str, object]) -> PairedAnalysisContract:
    outcomes = _mapping(plan, "outcomes")
    analysis = _mapping(plan, "analysis")

    expected = EXPECTED_ANALYSIS_CONTRACT
    checks = {
        "primary_endpoint": (outcomes.get("primary_endpoint"), expected.primary_endpoint),
        "primary_estimand": (outcomes.get("primary_estimand"), expected.primary_estimand),
        "analysis.unit": (analysis.get("unit"), expected.unit),
        "analysis.effect_direction": (analysis.get("effect_direction"), expected.effect_direction),
        "analysis.inferential_test": (analysis.get("inferential_test"), expected.inferential_test),
        "analysis.null_discordant_win_probability": (
            analysis.get("null_discordant_win_probability"),
            expected.null_discordant_win_probability,
        ),
        "analysis.alpha": (analysis.get("alpha"), expected.alpha),
        "analysis.final_analysis_requires_complete_schedule": (
            analysis.get("final_analysis_requires_complete_schedule"),
            expected.final_analysis_requires_complete_schedule,
        ),
        "analysis.excluded_attempts_never_count_as_completed_pairs": (
            analysis.get("excluded_attempts_never_count_as_completed_pairs"),
            expected.excluded_attempts_never_count_as_completed_pairs,
        ),
    }
    drift = [name for name, (observed, wanted) in checks.items() if observed != wanted]
    if drift:
        raise PairedAnalysisContractError(
            "paired primary analysis contract drifted: " + ",".join(drift)
        )

    required_true = (
        "paired",
        "report_discordant_pairs",
        "report_per_task_results",
        "report_aggregate_resolution_rate",
        "report_primary_paired_effect",
        "no_universal_weighted_score",
        "outcome_blind_plan_changes_required",
    )
    false_flags = [name for name in required_true if analysis.get(name) is not True]
    if false_flags:
        raise PairedAnalysisContractError(
            "paired analysis boolean invariant drifted: " + ",".join(false_flags)
        )
    return expected


def _mapping(source: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = source.get(name)
    if not isinstance(value, Mapping):
        raise PairedAnalysisContractError(f"{name} must be an object")
    return value
