"""One enrolled episode per arm. Failures never trigger task resampling."""
import difflib
import random
import time
from benchmark_core.identity import canonical_json, Sha256Digest
from .native import NativeDriver, stock_arm
from .provider.ledger import totals
from .evaluation import read_json


def patch_text(before, after):
    return ''.join(''.join(difflib.unified_diff(before.get(path, '').splitlines(True),
                     after.get(path, '').splitlines(True), fromfile='a/' + path, tofile='b/' + path))
                   for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path))


def run_episode(root, recipe, qualified, repetition, arm, docker, evaluator, token, settings, report, scratch):
    from .cycle import cycle_arm
    before = qualified["files"]
    directory = scratch / (recipe.task_id + f"-{repetition}-{arm}")
    directory.mkdir()
    started = time.monotonic()
    driver = NativeDriver(docker, directory, settings, token, started + settings.arm_seconds,
                          workspace_adapter=qualified.get("workspace_adapter"))
    candidate = before
    metadata = {}
    evaluator.deadline = driver.deadline
    try:
        if arm == "stock":
            candidate, metadata = stock_arm(driver, before, recipe.description)
        else:
            candidate, metadata = cycle_arm(driver, evaluator, before, recipe,
                qualified["public_checks"], qualified["public_expected"], directory, settings)
    except (OSError, ValueError, RuntimeError) as error:
        metadata = {"status": "EXECUTION_ERROR", "reason": str(error)[:1500], "invocations": driver.invocations}
        if arm == "stock" and driver.last_candidate is not None:
            candidate = driver.last_candidate
    finally:
        evaluator.deadline = None
    wall = time.monotonic() - started
    scored = evaluator.score(candidate, qualified["checks"], qualified["expected"])
    patch_ref = report.cas.put_text(patch_text(before, candidate))
    detail_ref = report.cas.put_text(canonical_json({"execution": metadata, "evaluation": scored}))
    delivered = metadata.get("status") in {"RETURNED", "CANDIDATE_READY"}
    passed = scored["status"] == "PASS"
    return {"task": recipe.task_id, "project": recipe.project_id, "repetition": repetition, "arm": arm,
            "input_digest": str(Sha256Digest.of(before)), "candidate_digest": str(Sha256Digest.of(candidate)),
            "execution": metadata.get("status"), "external_verdict": scored["status"], "delivered": delivered,
            "external_pass": passed, "solved": passed and delivered, "wall_seconds": round(wall, 3),
            "false_accept": delivered and scored["status"] == "FAIL", "false_reject": passed and not delivered,
            "patch_ref": patch_ref, "details_ref": detail_ref}


def with_usage(rows, provider_path):
    providers = read_json(provider_path, limit=16777216)
    enriched = []
    for row in rows:
        key = row["task"] + f":{row['repetition']}:{row['arm']}"
        usage = totals(providers[key])
        enriched.append({**row, "usage": {key: value for key, value in usage.items() if key != "records"}})
    return enriched


def schedule(qualified, repeats, seed):
    generator = random.Random(seed)
    scheduled = []
    for recipe, data in qualified:
        for repetition in range(repeats):
            order = ["stock", "cycle"]
            generator.shuffle(order)
            scheduled.extend((recipe, data, repetition, arm) for arm in order)
    return scheduled
