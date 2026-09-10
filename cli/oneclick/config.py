"""Strict immutable operator configuration; no task execution authority."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import math
import re
import tomllib


def integer(value, name: str, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= 100000:
        raise ValueError(f"{name} must be an integer in [{minimum}, 100000]")
    return value


def exact_keys(value: dict, names: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != names:
        raise ValueError(f"{name}: expected keys {sorted(names)}")


@dataclass(frozen=True)
class Budgets:
    test_seconds: int
    project_seconds: int
    build_seconds: int
    baseline_seconds: int
    max_api_requests: int
    api_seconds: int
    max_response_bytes: int
    planned_usd_per_episode: float


@dataclass(frozen=True)
class Discovery:
    language: str
    since: str
    max_repositories: int
    max_prs_per_repository: int
    min_stars: int
    licenses: tuple[str, ...]


@dataclass(frozen=True)
class Campaign:
    projects: tuple[str, ...]
    repetitions: int
    tasks_per_project: int
    seed: int
    arms: tuple[str, ...]
    quotas: tuple[tuple[str, int], ...]
    budgets: Budgets
    discovery: Discovery


def load_config(path: Path) -> Campaign:
    if path.stat().st_size > 65536:
        raise ValueError("Configuration exceeds 64 KiB")
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    exact_keys(data, {"schema", "projects", "repetitions", "tasks_per_project", "seed",
                      "arms", "quotas", "budgets", "discovery"}, "campaign")
    if data["schema"] != "autobench.campaign/v1":
        raise ValueError("Unsupported campaign schema")
    sequences = {}
    for name in ("projects", "arms"):
        values = data[name]
        if not isinstance(values, list) or not values or len(values) > 1000:
            raise ValueError(f"{name} must be a bounded nonempty list")
        if any(not isinstance(item, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", item) for item in values):
            raise ValueError(f"Invalid {name} identifier")
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate {name}")
        sequences[name] = tuple(values)
    if len(sequences["arms"]) != 2:
        raise ValueError("This planning profile requires exactly two distinct arms")
    exact_keys(data["quotas"], {"small", "medium", "large"}, "quotas")
    quotas = tuple((key, integer(value, f"quota.{key}", 0))
                   for key, value in sorted(data["quotas"].items()))
    if sum(value for _, value in quotas) == 0:
        raise ValueError("At least one project is required")
    budget = data["budgets"]
    exact_keys(budget, set(Budgets.__dataclass_fields__), "budgets")
    for name in set(budget) - {"planned_usd_per_episode", "max_response_bytes"}:
        integer(budget[name], name)
    if type(budget["max_response_bytes"]) is not int or not 1024 <= budget["max_response_bytes"] <= 8388608:
        raise ValueError("max_response_bytes must be 1 KiB..8 MiB")
    cost = budget["planned_usd_per_episode"]
    if type(cost) not in (int, float) or not math.isfinite(cost) or not 0 <= cost <= 10000:
        raise ValueError("Invalid planned cost ceiling")
    discovery = dict(data["discovery"])
    exact_keys(discovery, set(Discovery.__dataclass_fields__), "discovery")
    if not isinstance(discovery["language"], str) or not re.fullmatch(r"[A-Za-z0-9_+#.-]+", discovery["language"]):
        raise ValueError("Invalid language")
    date.fromisoformat(discovery["since"])
    for name in ("max_repositories", "max_prs_per_repository", "min_stars"):
        integer(discovery[name], name, 0 if name == "min_stars" else 1)
    licenses = discovery["licenses"]
    if not isinstance(licenses, list) or not licenses or any(not isinstance(x, str) or not x for x in licenses):
        raise ValueError("licenses must be nonempty SPDX strings")
    discovery["licenses"] = tuple(licenses)
    return Campaign(sequences["projects"], integer(data["repetitions"], "repetitions"),
                    integer(data["tasks_per_project"], "tasks_per_project"),
                    integer(data["seed"], "seed", 0), sequences["arms"], quotas,
                    Budgets(**budget), Discovery(**discovery))
