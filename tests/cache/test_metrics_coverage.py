import pytest

from benchmark_core.coverage import CandidateExperiment, greedy_select
from benchmark_core.metrics import MetricRegistry


def test_namespaced_metrics_and_no_universal_score():
    metrics = MetricRegistry(); metrics.record("auto_zoning.precision", 0.9)
    with pytest.raises(ValueError): metrics.record("score", 1)
    with pytest.raises(ValueError): metrics.record("core.overall", 1)


def test_greedy_coverage_prefers_cost_effective_candidate():
    result = greedy_select({"a", "b"}, [
        CandidateExperiment("both", frozenset({"a", "b"}), estimated_cost=1),
        CandidateExperiment("a", frozenset({"a"}), estimated_cost=1),
        CandidateExperiment("b", frozenset({"b"}), estimated_cost=1),
    ])
    assert [candidate.experiment_id for candidate in result.selected] == ["both"]
