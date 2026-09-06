"""Namespaced metrics; incomparable capabilities are never universally scored."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Mapping

_FORBIDDEN = {"score", "overall_score", "universal_score", "autonomous_dev_score", "total_score"}


@dataclass(frozen=True)
class Metric:
    name: str
    value: int | float | bool
    unit: str | None = None

    def __post_init__(self) -> None:
        validate_metric_name(self.name)
        if not isinstance(self.value, (Real, bool)): raise TypeError("metric value must be numeric or boolean")


def validate_metric_name(name: str) -> str:
    if not isinstance(name, str) or "." not in name or name.startswith(".") or name.endswith("."):
        raise ValueError("metric names must be namespaced (for example core.wall_time)")
    parts = name.lower().split(".")
    if name.lower() in _FORBIDDEN or any(part in {"universal", "overall"} for part in parts):
        raise ValueError("universal/overall scores are forbidden")
    if parts[-1] == "score" and parts[0] in {"core", "benchmark", "global", "all"}:
        raise ValueError("universal scores are forbidden")
    return name


class MetricRegistry:
    def __init__(self) -> None: self._metrics: dict[str, Metric] = {}
    def record(self, name: str, value: int | float | bool, unit: str | None = None) -> Metric:
        metric = Metric(name, value, unit); self._metrics[name] = metric; return metric
    def snapshot(self) -> Mapping[str, Metric]: return dict(self._metrics)
    def values(self) -> dict[str, int | float | bool]: return {name: metric.value for name, metric in sorted(self._metrics.items())}
