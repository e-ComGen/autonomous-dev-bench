"""Validate the deterministic Harbor <-> ADCP process-contract qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from suites.coding.adcp_contract import (
    ADCP_COMMIT,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
    parse_adcp_runner_receipt,
)


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase3c-adcp/PHASE3C_ADCP_FAKE_HARBOR.json"),
    )
    args = parser.parse_args()

    result_path = unique_file(args.trials_dir, "result.json")
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    receipt_path = unique_file(args.trials_dir, "ADCP_RESULT.json")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    raw_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    patch = patch_path.read_text(encoding="utf-8")
    receipt = parse_adcp_runner_receipt(
        raw_receipt,
        allow_fake_runtime=True,
        require_repair_cycle=True,
    )

    if result.get("exception_info") is not None:
        raise ValueError(f"Harbor ADCP trial contains exception: {result['exception_info']}")
    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        raise ValueError("Harbor ADCP trial did not persist AgentContext")
    for name, expected in (
        ("n_input_tokens", 0),
        ("n_output_tokens", 0),
        ("n_cache_tokens", 0),
        ("cost_usd", 0.0),
    ):
        if agent_result.get(name) != expected:
            raise ValueError(f"fake ADCP AgentContext {name} mismatch: {agent_result.get(name)!r}")

    metadata = agent_result.get("metadata")
    bench = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(bench, dict):
        raise ValueError("ADCP Harbor AgentContext metadata missing")
    if bench.get("agent") != "adcp":
        raise ValueError("unexpected Harbor agent identity")
    if bench.get("fake_runtime") is not True or bench.get("runtime_loaded") is not False:
        raise ValueError("fake qualification blurred fake/private runtime identity")
    if bench.get("model_called") is not False:
        raise ValueError("fake ADCP qualification unexpectedly called a model")
    if bench.get("model_calls_via_budget_proxy") is not True:
        raise ValueError("ADCP receipt did not preserve budget-proxy routing")
    if bench.get("upstream_provider_credential_present") is not False:
        raise ValueError("ADCP task environment exposed an upstream provider credential")
    if bench.get("candidate_ready") is not True or bench.get("task_completed") is not False:
        raise ValueError("CANDIDATE_READY/TASK_COMPLETED boundary was not preserved")
    if bench.get("repair_count") != 1:
        raise ValueError("fake qualification did not preserve one repair cycle")

    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"Harbor verifier did not return full reward: {rewards!r}")

    if "-baseline" not in patch or "+adcp candidate ready after repair" not in patch:
        raise ValueError("actual Harbor patch does not contain the fake candidate mutation")
    patch_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if bench.get("patch_sha256") != patch_sha:
        raise ValueError("Harbor metadata patch digest differs from independently exported patch")

    harbor_lock = json.loads(args.harbor_lock.read_text(encoding="utf-8"))
    evidence = {
        "schema_version": 1,
        "scope": "PHASE3C_ADCP_HARBOR_PROCESS_CONTRACT_FAKE_RUNTIME",
        "status": "PASS",
        "private_runtime_loaded": False,
        "fake_runtime": True,
        "paid_model_called": False,
        "model_calls_via_budget_proxy": True,
        "upstream_provider_credential_present": False,
        "target_private_runtime": {
            "repository": ADCP_REPOSITORY,
            "commit": ADCP_COMMIT,
            "runtime": ADCP_RUNTIME,
        },
        "role_ids_distinct": len(set(receipt.role_ids.values())) == 4,
        "role_call_counts": dict(receipt.role_call_counts),
        "event_sequence": list(receipt.event_sequence),
        "repair_count": receipt.repair_count,
        "candidate_ready": receipt.candidate_ready,
        "task_completed": receipt.task_completed,
        "harbor": {
            "version": harbor_lock["version"],
            "commit": harbor_lock["commit"],
        },
        "trial": {
            "task_name": result.get("task_name"),
            "trial_name": result.get("trial_name"),
            "task_checksum": result.get("task_checksum"),
            "agent_info": result.get("agent_info"),
            "verifier_result": verifier,
        },
        "patch_sha256": patch_sha,
        "patch_bytes": len(patch.encode("utf-8")),
        "production_ready": False,
        "production_blocker": "PINNED_PRIVATE_ADCP_RUNTIME_NOT_QUALIFIED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 3C fake ADCP Harbor boundary: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
