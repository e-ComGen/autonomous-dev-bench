"""Validate a completed no-model Harbor substrate qualification trial."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/harbor-phase2/PHASE2_HARBOR_SUBSTRATE.json"))
    args = parser.parse_args()

    lock = json.loads(args.harbor_lock.read_text(encoding="utf-8"))
    result_path = unique_file(args.trials_dir, "result.json")
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    probe_path = unique_file(args.trials_dir, "PROBE.json")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    patch = patch_path.read_text(encoding="utf-8")

    if result.get("exception_info") is not None:
        raise ValueError(f"Harbor trial contains exception: {result['exception_info']}")
    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        raise ValueError("Harbor trial did not persist AgentContext")
    expected_usage = {
        "n_input_tokens": 0,
        "n_cache_tokens": 0,
        "n_output_tokens": 0,
        "cost_usd": 0.0,
    }
    for key, expected in expected_usage.items():
        if agent_result.get(key) != expected:
            raise ValueError(f"Harbor AgentContext {key} mismatch: {agent_result.get(key)!r}")
    metadata = agent_result.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("autonomous_dev_bench"), dict):
        raise ValueError("Harbor AgentContext metadata was not preserved")
    if metadata["autonomous_dev_bench"].get("model_called") is not False:
        raise ValueError("substrate probe unexpectedly reports a model call")

    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"Harbor verifier did not return full reward: {rewards!r}")

    baseline = probe.get("baseline_commit")
    if not isinstance(baseline, str) or not COMMIT_RE.fullmatch(baseline):
        raise ValueError("probe did not record an exact git baseline commit")
    if probe.get("model_called") is not False or not probe.get("instruction_received"):
        raise ValueError("probe execution identity is incomplete")
    if not isinstance(probe.get("environment_id"), str) or not probe["environment_id"]:
        raise ValueError("Harbor environment_id was not exposed to the external agent")
    if "-baseline" not in patch or "+harbor substrate qualified" not in patch:
        raise ValueError("exported patch does not contain the expected repository mutation")

    evidence = {
        "scope": "PHASE2_HARBOR_SUBSTRATE_NO_MODEL",
        "status": "PASS",
        "model_called": False,
        "harbor": lock,
        "trial": {
            "task_name": result.get("task_name"),
            "trial_name": result.get("trial_name"),
            "task_checksum": result.get("task_checksum"),
            "agent_info": result.get("agent_info"),
            "agent_result": agent_result,
            "verifier_result": verifier,
        },
        "environment_id": probe["environment_id"],
        "baseline_commit": baseline,
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "patch_bytes": len(patch.encode("utf-8")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Harbor Phase 2 substrate: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
