"""Run both existing execution paths on enrolled GitHub issues without resampling failures."""
import json
import os
import secrets
from dataclasses import asdict
from .experiment import run_episode, schedule, with_usage
from .spend import authorize
from corpus.qualification.workspace import RepositoryWorkspace


def run_pairs(root, docker, prepared, settings, report, seed, allowed, result):
    scheduled = schedule(prepared, settings.repeats, seed)
    result["enrolled_episodes"] = len(scheduled)
    tokens = {secrets.token_hex(24): task.task_id + f":{repetition}:{arm}"
              for task, _, repetition, arm in scheduled}
    inverse = {value: key for key, value in tokens.items()}
    result["order"] = [{"task": task.task_id, "repetition": repetition, "arm": arm}
                       for task, _, repetition, arm in scheduled]
    key = authorize(settings, len(scheduled), allowed)
    previous = os.environ.get("DEEPSEEK_API_KEY")
    try:
        os.environ["DEEPSEEK_API_KEY"] = key
        provider_path = docker.start_relay(tokens)
    finally:
        if previous is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = previous
        key = None
    result["status"] = "RUNNING"
    report.save(result)
    try:
        for task, data, repetition, arm in scheduled:
            data["workspace_adapter"] = RepositoryWorkspace(data["captured"]["base_files"], settings.max_patch_bytes)
            token = inverse[task.task_id + f":{repetition}:{arm}"]
            docker.image = data["image"]
            row = run_episode(root, task, data, repetition, arm, docker, data["evaluator"], token,
                              settings, report, docker.scratch)
            result["rows"].append(row)
            result["rows"] = with_usage(result["rows"], provider_path)
            result["live_model_called"] = any(row["usage"]["model_requests"] for row in result["rows"])
            print(f"{arm}: {row['external_verdict']}; delivered={row['delivered']}; {row['wall_seconds']}s", flush=True)
            report.save(result)
    finally:
        raw = provider_path.read_text(encoding="utf-8")
        result["provider_receipt"] = report.cas.put_text(raw)
        result["live_model_called"] = any(value["admitted"] for value in json.loads(raw).values())
    result["status"] = "AB_COMPLETE" if result["live_model_called"] else "AB_INCOMPLETE"
    result["comparison"] = {arm: {
        "episodes": sum(row["arm"] == arm for row in result["rows"]),
        "solved": sum(row["solved"] for row in result["rows"] if row["arm"] == arm),
        "external_pass": sum(row["external_pass"] for row in result["rows"] if row["arm"] == arm),
        "cost_usd": None,
    } for arm in ("stock", "cycle")}
