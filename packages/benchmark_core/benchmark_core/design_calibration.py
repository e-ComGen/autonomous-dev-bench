"""Outcome-blind design calibration for the preregistered paired experiment.

This module selects a repeat count from explicit pre-experiment assumptions using
exact power under the already-locked two-sided McNemar/binomial analysis. It does
not inspect experiment outcomes and it never invents model/resource budgets.

The companion plan compiler fills only the previously-declared design blanks and
records the assumptions/provenance used to do so. External admission gates remain
independent; a statistically locked design is not sufficient for paid readiness.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Mapping

from .identity import CanonicalModel, Sha256Digest
from .paired_analysis import exact_mcnemar_two_sided
from .paired_analysis_contract import ANALYSIS_ALPHA


CALIBRATION_METHOD = "exact-mcnemar-random-discordance-v1"
ALLOWED_ASSUMPTION_SOURCES = frozenset(
    {
        "external_prior",
        "preexperiment_pilot",
        "budget_sensitivity_scenario",
    }
)


class DesignCalibrationError(ValueError):
    """Calibration input is invalid or would violate the preregistered design."""


class DesignPowerUnavailable(RuntimeError):
    """The requested power cannot be reached within the predeclared search bound."""


@dataclass(frozen=True, slots=True)
class CalibrationAssumptions(CanonicalModel):
    expected_discordant_rate: float
    adcp_win_probability_given_discordance: float
    target_power: float
    max_repeat_count: int
    assumption_source: str
    assumption_reference: str
    alpha: float = ANALYSIS_ALPHA
    method: str = CALIBRATION_METHOD

    def __post_init__(self) -> None:
        _open_probability(self.expected_discordant_rate, "expected_discordant_rate", allow_one=True)
        _open_probability(
            self.adcp_win_probability_given_discordance,
            "adcp_win_probability_given_discordance",
            allow_one=True,
        )
        if self.adcp_win_probability_given_discordance == 0.5:
            raise DesignCalibrationError(
                "adcp_win_probability_given_discordance must differ from the null value 0.5"
            )
        _open_probability(self.target_power, "target_power", allow_one=False)
        if self.alpha != ANALYSIS_ALPHA:
            raise DesignCalibrationError(
                f"alpha must equal preregistered analysis alpha {ANALYSIS_ALPHA}"
            )
        if self.method != CALIBRATION_METHOD:
            raise DesignCalibrationError("unsupported calibration method")
        if isinstance(self.max_repeat_count, bool) or not isinstance(self.max_repeat_count, int) or self.max_repeat_count <= 0:
            raise DesignCalibrationError("max_repeat_count must be a positive integer")
        if self.assumption_source not in ALLOWED_ASSUMPTION_SOURCES:
            raise DesignCalibrationError(
                "assumption_source must be an explicitly pre-experiment source"
            )
        if not isinstance(self.assumption_reference, str) or not self.assumption_reference.strip():
            raise DesignCalibrationError("assumption_reference must be non-empty")


@dataclass(frozen=True, slots=True)
class ResourceCaps(CanonicalModel):
    total_model_token_cap_per_arm: int
    input_token_cap_per_arm: int
    output_token_cap_per_arm: int
    max_requests_per_arm: int
    wall_time_seconds_per_arm: int
    patch_byte_cap_per_arm: int

    def __post_init__(self) -> None:
        for name in (
            "total_model_token_cap_per_arm",
            "input_token_cap_per_arm",
            "output_token_cap_per_arm",
            "max_requests_per_arm",
            "wall_time_seconds_per_arm",
            "patch_byte_cap_per_arm",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise DesignCalibrationError(f"{name} must be a positive integer")
        if self.input_token_cap_per_arm > self.total_model_token_cap_per_arm:
            raise DesignCalibrationError("input token cap cannot exceed primary total-token cap")
        if self.output_token_cap_per_arm > self.total_model_token_cap_per_arm:
            raise DesignCalibrationError("output token cap cannot exceed primary total-token cap")


@dataclass(frozen=True, slots=True)
class CalibrationResult(CanonicalModel):
    task_count: int
    repeat_count_per_task: int
    total_pair_count: int
    achieved_power: float
    target_power: float
    expected_discordant_pairs: float
    implied_resolution_rate_difference: float
    assumptions_digest: Sha256Digest
    method: str = CALIBRATION_METHOD

    def __post_init__(self) -> None:
        if not isinstance(self.assumptions_digest, Sha256Digest):
            object.__setattr__(
                self,
                "assumptions_digest",
                Sha256Digest(str(self.assumptions_digest)),
            )


def exact_paired_power(total_pairs: int, assumptions: CalibrationAssumptions) -> float:
    """Exact unconditional power for the preregistered two-sided McNemar test.

    D ~ Binomial(total_pairs, expected_discordant_rate) is the number of
    discordant pairs. Conditional on D=d, X ~ Binomial(d, p) is the number of
    discordant pairs won by ADCP. We average the exact rejection probability over
    both distributions; no normal approximation is used.
    """
    if isinstance(total_pairs, bool) or not isinstance(total_pairs, int) or total_pairs <= 0:
        raise DesignCalibrationError("total_pairs must be a positive integer")

    q = assumptions.expected_discordant_rate
    p = assumptions.adcp_win_probability_given_discordance

    # When q=1, D is deterministically total_pairs. Skipping impossible
    # discordant counts preserves the exact calculation while avoiding the
    # quadratic family of conditional tests needed by the general mixture.
    if q == 1.0:
        return _conditional_rejection_probability(total_pairs, p, assumptions.alpha)

    conditional_reject = tuple(
        _conditional_rejection_probability(discordant, p, assumptions.alpha)
        for discordant in range(total_pairs + 1)
    )
    power = 0.0
    for discordant in range(total_pairs + 1):
        power += _binomial_pmf(total_pairs, discordant, q) * conditional_reject[discordant]
    return min(1.0, max(0.0, power))


def calibrate_repeat_count(
    *,
    task_count: int,
    assumptions: CalibrationAssumptions,
) -> CalibrationResult:
    """Select the smallest equal per-task repeat count meeting target power."""
    if isinstance(task_count, bool) or not isinstance(task_count, int) or task_count <= 0:
        raise DesignCalibrationError("task_count must be a positive integer")

    selected_repeat: int | None = None
    selected_power = 0.0
    for repeat_count in range(1, assumptions.max_repeat_count + 1):
        total_pairs = task_count * repeat_count
        power = exact_paired_power(total_pairs, assumptions)
        if power >= assumptions.target_power:
            selected_repeat = repeat_count
            selected_power = power
            break

    if selected_repeat is None:
        final_pairs = task_count * assumptions.max_repeat_count
        final_power = exact_paired_power(final_pairs, assumptions)
        raise DesignPowerUnavailable(
            "target power is not reachable within max_repeat_count; "
            f"pairs={final_pairs}, achieved_power={final_power:.12f}, "
            f"target_power={assumptions.target_power:.12f}"
        )

    total_pairs = task_count * selected_repeat
    return CalibrationResult(
        task_count=task_count,
        repeat_count_per_task=selected_repeat,
        total_pair_count=total_pairs,
        achieved_power=selected_power,
        target_power=assumptions.target_power,
        expected_discordant_pairs=total_pairs * assumptions.expected_discordant_rate,
        implied_resolution_rate_difference=(
            assumptions.expected_discordant_rate
            * (2.0 * assumptions.adcp_win_probability_given_discordance - 1.0)
        ),
        assumptions_digest=assumptions.content_digest,
    )


def compile_locked_plan(
    plan: Mapping[str, object],
    *,
    assumptions: CalibrationAssumptions,
    caps: ResourceCaps,
) -> dict[str, object]:
    """Fill the outcome-blind design blanks and emit a deterministic LOCKED plan.

    The function intentionally refuses an already-locked plan and refuses plans
    that contain unexpected prefilled design values. This makes calibration a
    one-way preregistration event rather than a convenient post-outcome editor.
    """
    if not isinstance(plan, Mapping):
        raise DesignCalibrationError("plan must be an object")
    result_plan = deepcopy(dict(plan))
    if result_plan.get("status") != "DRAFT_BLOCKED":
        raise DesignCalibrationError("only a DRAFT_BLOCKED plan can be calibrated")
    if result_plan.get("paid_paired_ab") != "NOT_RUN" or result_plan.get("winner") != "UNKNOWN":
        raise DesignCalibrationError("calibration is forbidden after experiment outcomes exist")

    corpus = _required_mapping(result_plan, "corpus")
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or not tasks or any(not isinstance(item, str) for item in tasks):
        raise DesignCalibrationError("plan corpus tasks must be a non-empty string list")
    if len(tasks) != len(set(tasks)):
        raise DesignCalibrationError("plan corpus contains duplicate tasks")

    execution = _required_mapping(result_plan, "execution")
    budget = _required_mapping(result_plan, "budget")
    stopping = _required_mapping(result_plan, "stopping")
    _require_unset(execution, "repeat_count_per_task")
    _require_unset(stopping, "required_completed_pairs")
    for field in (
        "total_model_token_cap_per_arm",
        "input_token_cap_per_arm",
        "output_token_cap_per_arm",
        "max_requests_per_arm",
        "wall_time_seconds_per_arm",
        "patch_byte_cap_per_arm",
    ):
        _require_unset(budget, field)

    calibration = calibrate_repeat_count(task_count=len(tasks), assumptions=assumptions)
    execution["repeat_count_per_task"] = calibration.repeat_count_per_task
    stopping["required_completed_pairs"] = calibration.total_pair_count
    for field in (
        "total_model_token_cap_per_arm",
        "input_token_cap_per_arm",
        "output_token_cap_per_arm",
        "max_requests_per_arm",
        "wall_time_seconds_per_arm",
        "patch_byte_cap_per_arm",
    ):
        budget[field] = getattr(caps, field)

    result_plan["status"] = "LOCKED"
    result_plan["design_paid_ready"] = True
    result_plan["design_blockers"] = []
    result_plan["calibration"] = {
        "method": CALIBRATION_METHOD,
        "assumptions": _canonical_plain(assumptions),
        "assumptions_digest": str(calibration.assumptions_digest),
        "resource_caps": _canonical_plain(caps),
        "result": _canonical_plain(calibration),
        "outcome_data_used": False,
        "paid_model_called": False,
    }
    return result_plan


def canonical_json_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_plain(model: CanonicalModel) -> dict[str, object]:
    value = json.loads(model.to_canonical_json())
    if not isinstance(value, dict):
        raise DesignCalibrationError("canonical model did not serialize to an object")
    return value


def _conditional_rejection_probability(discordant: int, p: float, alpha: float) -> float:
    if discordant == 0:
        return 0.0
    probability = 0.0
    for adcp_only in range(discordant + 1):
        stock_only = discordant - adcp_only
        p_value = exact_mcnemar_two_sided(stock_only=stock_only, adcp_only=adcp_only)
        if p_value < alpha:
            probability += _binomial_pmf(discordant, adcp_only, p)
    return probability


def _binomial_pmf(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p**k) * ((1.0 - p) ** (n - k))


def _open_probability(value: object, name: str, *, allow_one: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesignCalibrationError(f"{name} must be numeric")
    numeric = float(value)
    upper_ok = numeric <= 1.0 if allow_one else numeric < 1.0
    if numeric <= 0.0 or not upper_ok or not math.isfinite(numeric):
        bound = "(0,1]" if allow_one else "(0,1)"
        raise DesignCalibrationError(f"{name} must be in {bound}")
    return numeric


def _required_mapping(source: dict[str, object], name: str) -> dict[str, object]:
    value = source.get(name)
    if not isinstance(value, dict):
        raise DesignCalibrationError(f"plan {name} must be an object")
    return value


def _require_unset(source: Mapping[str, object], name: str) -> None:
    if source.get(name) is not None:
        raise DesignCalibrationError(f"{name} is already set; outcome-blind calibration refuses overwrite")
