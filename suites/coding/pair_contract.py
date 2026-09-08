"""Freeze the experiment's common inputs and budgets, without owning agent execution."""
from dataclasses import asdict
from benchmark_core.identity import Sha256Digest


def input_binding(task, data):
    return {"task": task.task_id, "project": task.project_id,
            "objective_digest": str(Sha256Digest.of(task.description)),
            "input_digest": str(Sha256Digest.of(data["files"])),
            "environment": data["image"],
            "base_source_digest": data["captured"]["base_source_digest"]}


def freeze_pair_contract(prepared, settings):
    bindings = [input_binding(task, data) for task, data in prepared]
    if len(bindings) != settings.tasks or len({item["task"] for item in bindings}) != len(bindings):
        raise ValueError("PAIR_TASK_IDENTITY_MISMATCH")
    return {"schema": "autobench.pair_contract/v1", "tasks": bindings,
            "model": settings.model, "harness_profile": "sdk", "repeats": settings.repeats,
            "settings_digest": str(Sha256Digest.of(asdict(settings))),
            "limits_apply_to": "ENTIRE_ARM_INCLUDING_ALL_ADCP_ROLES_AND_NATIVE_RETRIES",
            "requests_per_arm": settings.requests_per_arm,
            "output_tokens_per_request": settings.output_tokens_per_request,
            "maximum_requested_output_tokens_per_arm": settings.requests_per_arm * settings.output_tokens_per_request,
            "request_bytes": settings.request_bytes, "wall_seconds_per_arm": settings.arm_seconds,
            "hard_input_token_cap": None, "hard_dollar_cap": None,
            "enrolled_episodes": len(bindings) * settings.repeats * 2}


def assert_episode_binding(contract, task, data, settings):
    expected = [item for item in contract["tasks"] if item["task"] == task.task_id]
    if expected != [input_binding(task, data)]:
        raise ValueError("PAIRED_INPUT_CHANGED_AFTER_ENROLLMENT")
    if contract["settings_digest"] != str(Sha256Digest.of(asdict(settings))):
        raise ValueError("PAIRED_BUDGET_CHANGED_AFTER_ENROLLMENT")


def validate_pair_rows(contract, rows):
    expected = {(task["task"], repetition, arm): task for task in contract["tasks"]
                for repetition in range(contract["repeats"]) for arm in ("stock", "cycle")}
    seen = set()
    for row in rows:
        key = row["task"], row["repetition"], row["arm"]
        if key not in expected or key in seen:
            raise ValueError("PAIR_RESULT_IDENTITY_MISMATCH")
        seen.add(key)
        if row["input_digest"] != expected[key]["input_digest"] or row["project"] != expected[key]["project"]:
            raise ValueError("PAIR_RESULT_SOURCE_MISMATCH")
        usage = row["usage"]
        requests = usage["model_requests"]
        if type(requests) is not int or not 0 <= requests <= contract["requests_per_arm"]:
            raise ValueError("PAIR_REQUEST_BUDGET_EXCEEDED")
        output = usage.get("output_tokens")
        if output is not None and (type(output) is not int or not 0 <= output <= contract["maximum_requested_output_tokens_per_arm"]):
            raise ValueError("PROVIDER_OUTPUT_EXCEEDS_RECORDED_CAP")
    if seen != set(expected):
        raise ValueError("PAIR_RESULTS_MISSING")
    return {"same_input_confirmed": True, "same_settings_confirmed": True,
            "request_caps_respected": True, "episodes_retained": len(rows),
            "usage_complete": all(row["usage"].get("usage_complete", False) for row in rows)}
