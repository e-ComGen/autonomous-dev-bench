"""A random draw from the eligible public-seed universe, frozen before either arm."""
import random
from dataclasses import asdict
from benchmark_core.identity import Sha256Digest
from .recipes import RECIPES


def candidate_order(projects, seed):
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("Seed must be an unsigned 64-bit integer")
    generator = random.Random(seed)
    pools = {project: [item for item in RECIPES if item.project_id == project] for project in projects}
    pools = {key: list(value) for key, value in pools.items() if value}
    selected = []
    while pools:
        project = generator.choice(sorted(pools))
        choices = pools[project]
        index = generator.randrange(len(choices))
        selected.append(choices.pop(index))
        if not choices:
            del pools[project]
    return selected


def selection_digest(selected, settings):
    return str(Sha256Digest.of({"settings": asdict(settings), "tasks": [asdict(item) for item in selected]}))
