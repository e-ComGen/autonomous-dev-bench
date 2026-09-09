from __future__ import annotations

import math

import pytest

from benchmark_core.design_calibration import CalibrationAssumptions, exact_paired_power
from benchmark_core.paired_analysis import exact_mcnemar_two_sided


def _assumptions(p: float) -> CalibrationAssumptions:
    return CalibrationAssumptions(
        expected_discordant_rate=1.0,
        adcp_win_probability_given_discordance=p,
        target_power=0.8,
        max_repeat_count=100,
        assumption_source="budget_sensitivity_scenario",
        assumption_reference="phase3d7:q1-fastpath-equivalence",
    )


def _direct_conditional_power(n: int, p: float) -> float:
    probability = 0.0
    for adcp_only in range(n + 1):
        stock_only = n - adcp_only
        if exact_mcnemar_two_sided(stock_only=stock_only, adcp_only=adcp_only) < 0.05:
            probability += math.comb(n, adcp_only) * (p**adcp_only) * ((1.0 - p) ** stock_only)
    return probability


@pytest.mark.parametrize("n,p", [(6, 1.0), (30, 0.6), (70, 0.575), (100, 0.55)])
def test_q1_fast_path_is_exactly_the_deterministic_discordance_case(n: int, p: float) -> None:
    assert exact_paired_power(n, _assumptions(p)) == pytest.approx(
        _direct_conditional_power(n, p),
        abs=1e-15,
    )
