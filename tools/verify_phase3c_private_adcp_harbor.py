"""Validate sanitized evidence from the real pinned private ADCP Harbor qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from suites.coding.adcp_contract import (
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
    parse_adcp_runner_receipt,
)


EXPECTED_COUNTS = {"architect": 1, "coder": 2, "reviewer": 2, "verifier": 2}
EXPECTED_SEQUENCE = [
    "ARCHITECT",
    "CODER",
    "REVIEWER",
    "VERIFIER",
    "BADC_REPAIR",
    "CODER",
    "REVIEWER",
    "VERIFIER",
    "CANDIDATE_READY",
]


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--benchmark-commit", required=True)
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.source_commit != ADCP_COMMIT:
        raise ValueError("private qualification source commit differs from ADCP.lock identity")
    if len(args.source_tree) != 40 or any(ch not in "0123456789abcdef" for ch in args.source_tree.lower()):
        raise ValueError("invalid private source tree id")
    if len(args.benchmark_commit) != 40:
        raise ValueError("invalid benchmark commit id")

    result_path = unique_file(args.trials_dir, "result.json")
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    receipt_path = unique_file(args.trials_dir, "ADCP_RESULT.json")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    raw_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    patch = patch_path.read_text(encoding="utf-8")
    receipt = parse_adcp_runner_receipt(raw_receipt)

    if result.get("exception_info") is not None:
        raise ValueError(f"Harbor private ADCP trial contains exception: {result['exception_info']}")
    if receipt.fake_runtime or not receipt.runtime_loaded:
        raise ValueError("3C2 requires the real pinned private runtime")
    if receipt.repair_count != 1:
        raise ValueError("3C2 did not exercise exactly one real bounded repair")
    if dict(receipt.role_call_counts) != EXPECTED_COUNTS:
        raise ValueError(f"unexpected real Harness role-call counts: {receipt.role_call_counts!r}")
    if list(receipt.event_sequence) != EXPECTED_SEQUENCE:
        raise ValueError(f"unexpected real Harness event projection: {receipt.event_sequence!r}")
    if len(set(receipt.role_ids.values())) != 4:
        raise ValueError("real private runtime did not preserve four distinct role identities")
    if receipt.model_called:
        raise ValueError("3C2 qualification must not make a paid model call")
    if not receipt.model_calls_via_budget_proxy or receipt.upstream_provider_credential_present:
        raise ValueError("3C2 violated the budget-proxy credential boundary")
    if not receipt.candidate_ready or receipt.task_completed:
        raise ValueError("3C2 violated CANDIDATE_READY != TASK_COMPLETED")

    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        raise ValueError("Harbor did not persist ADCP AgentContext")
    for name, expected in (
        ("n_input_tokens", 0),
        ("n_output_tokens", 0),
        ("n_cache_tokens", 0),
        ("cost_usd", 0.0),
    ):
        if agent_result.get(name) != expected:
            raise ValueError(f"no-model private qualification {name} mismatch: {agent_result.get(name)!r}")
    metadata = agent_result.get("metadata")
    bench = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(bench, dict):
        raise ValueError("private ADCP Harbor metadata missing")
    if bench.get("fake_runtime") is not False or bench.get("runtime_loaded") is not True:
        raise ValueError("Harbor metadata does not identify the real private runtime")
    if bench.get("target_runtime") != {
        "repository": ADCP_REPOSITORY,
        "commit": ADCP_COMMIT,
        "runtime": ADCP_RUNTIME,
        "integration": ADCP_INTEGRATION,
    }:
        raise ValueError("Harbor metadata private target identity mismatch")

    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"Harbor private verifier did not return full reward: {rewards!r}")

    if "zone_a/pricing.py" not in patch or "discount(quantity)" not in patch or "- 2" not in patch:
        raise ValueError("actual Harbor patch does not contain the repaired pricing candidate")
    if "zone_b/owned.py" in patch:
        raise ValueError("actual Harbor patch modified the foreign Zone file")
    patch_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if bench.get("patch_sha256") != patch_sha:
        raise ValueError("Harbor metadata patch digest differs from independently exported patch")

    harbor_lock = json.loads(args.harbor_lock.read_text(encoding="utf-8"))
    evidence = {
        "schema_version": 1,
        "scope": "PHASE3C2_PINNED_PRIVATE_ADCP_ASSURED_RUNTIME_HARBOR",
        "status": "PASS",
        "private_runtime_loaded": True,
        "fake_runtime": False,
        "private_source_uploaded_to_public_artifact": False,
        "paid_model_called": False,
        "model_calls_via_budget_proxy": True,
        "upstream_provider_credential_present": False,
        "source": {
            "repository": ADCP_REPOSITORY,
            "commit": args.source_commit,
            "tree": args.source_tree,
        },
        "benchmark_commit": args.benchmark_commit,
        "runtime": ADCP_RUNTIME,
        "integration": ADCP_INTEGRATION,
        "role_ids_distinct": True,
        "role_ids": dict(receipt.role_ids),
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
            "verifier_result": verifier,
        },
        "patch_sha256": patch_sha,
        "patch_bytes": len(patch.encode("utf-8")),
        "private_runtime_qualification_status": "PASS",
        "production_paid_ready": False,
        "remaining_blocker": "LIVE_PROVIDER_PROMPT_USAGE_PARITY_NOT_RUN",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 3C2 pinned private ADCP runtime: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
