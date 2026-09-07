"""Pure, deterministic sampling. Planned slots are not qualified experiments."""
from dataclasses import asdict
import hashlib
from benchmark_core.identity import Sha256Digest
from .catalog import CatalogEntry
from .config import Campaign


def make_plan(config: Campaign, catalog: tuple[CatalogEntry, ...]) -> dict:
    by_id = {item.project_id: item for item in catalog}
    unknown = set(config.projects) - set(by_id)
    if unknown:
        raise ValueError(f"Unknown projects: {sorted(unknown)}")
    selected = []
    deficits = {}
    for scale, required in config.quotas:
        candidates = [by_id[key] for key in config.projects if by_id[key].scale == scale]
        candidates.sort(key=lambda item: hashlib.sha256(
            f"{config.seed}:{item.project_id}".encode()).hexdigest())
        chosen = candidates[:required]
        selected.extend(chosen)
        if len(chosen) < required:
            deficits[scale] = required - len(chosen)
    tasks = len(selected) * config.tasks_per_project
    requested = tasks * config.repetitions * len(config.arms)
    return {
        "kind": "CAMPAIGN_PLAN", "status": "PLAN_ONLY", "authoritative": False,
        "config_digest": str(Sha256Digest.of(asdict(config))),
        "projects": [{"id": item.project_id, "scale": item.scale,
                      "commit": item.commit, "manifest_digest": item.manifest_digest}
                     for item in selected],
        "classification_basis": "EXISTING_DECLARED_SCALE_NOT_MEASURED_LOC",
        "quota_deficits": deficits, "quota_satisfied": not deficits,
        "requested_task_slots": tasks, "requested_episode_slots": requested,
        "arms": list(config.arms), "repetitions": config.repetitions,
        "planned_max_api_usd": requested * config.budgets.planned_usd_per_episode,
        "actual_api_usd": None, "api_budget_enforced": False,
        "qualified_coding_tasks": 0, "executed_episodes": 0,
        "execution_ready": False,
        "blockers": ["CODING_TASK_QUALIFICATION_NOT_CONNECTED", "LIVE_ARMS_NOT_CONNECTED"],
    }
