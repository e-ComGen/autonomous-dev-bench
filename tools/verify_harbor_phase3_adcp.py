"""Validate the Phase 3 ADCP transport boundary without a model call."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from suites.coding.harbor.adcp_contract import (
    ADCPRuntimeResult,
    ADCP_RUNTIME_COMMIT,
    ADCP_RUNTIME_ENTRYPOINT,
    ADCP_RUNTIME_REPOSITORY,
    ADCP_INTEGRATION,
    SHARED_MODEL_ROUTE,
)


FAKE_GATEWAY_TOKEN = b"PHASE3_FAKE_GATEWAY_TOKEN_DO_NOT_PERSIST"
EXPECTED_FILE = "adcp-candidate.txt"
EXPECTED_CONTENT = "committed by phase3 ADCP transport stub"


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def full_reward(result: dict[str, object]) -> None:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"ADCP transport verifier did not return full reward: {rewards!r}")


def require_no_secret(root: Path) -> None:
    leaked: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if FAKE_GATEWAY_TOKEN in payload:
            leaked.append(str(path.relative_to(root)))
    if leaked:
        raise ValueError(f"gateway client token leaked into Harbor trial artifacts: {leaked}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/harbor-phase3/PHASE3_ADCP_TRANSPORT.json"),
    )
    args = parser.parse_args()

    result = load_json(unique_file(args.trials_dir, "result.json"))
    runtime_payload = load_json(unique_file(args.trials_dir, "ADCP_RESULT.json"))
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    patch = patch_path.read_text(encoding="utf-8")

    if result.get("exception_info") is not None:
        raise ValueError(f"ADCP Harbor trial failed: {result['exception_info']}")
    full_reward(result)

    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict) or agent_info.get("name") != "adcp-pinned-runtime":
        raise ValueError(f"unexpected Harbor agent identity: {agent_info!r}")

    context = result.get("agent_result")
    if not isinstance(context, dict):
        raise ValueError("Harbor did not persist ADCP AgentContext")
    metadata = context.get("metadata")
    benchmark_meta = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(benchmark_meta, dict):
        raise ValueError("ADCP benchmark metadata is missing")

    runtime = ADCPRuntimeResult.from_mapping(runtime_payload)
    if runtime.metadata.get("qualification_stub") is not True or runtime.metadata.get("paid_model_called") is not False:
        raise ValueError("transport task did not identify itself as a no-model qualification stub")
    if runtime.model_accounting.total_model_tokens != 0 or runtime.model_accounting.requests != 0:
        raise ValueError("no-model ADCP transport unexpectedly recorded model usage")

    expected_identity = {
        "runtime_repository": ADCP_RUNTIME_REPOSITORY,
        "runtime_commit": ADCP_RUNTIME_COMMIT,
        "runtime_entrypoint": ADCP_RUNTIME_ENTRYPOINT,
        "runtime_integration": ADCP_INTEGRATION,
        "model_route": SHARED_MODEL_ROUTE,
        "direct_model_api_used": False,
        "adcp_outcome": "CANDIDATE_READY",
        "model_accounting_valid": True,
    }
    mismatches = {
        key: {"expected": expected, "observed": benchmark_meta.get(key)}
        for key, expected in expected_identity.items()
        if benchmark_meta.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"ADCP Harbor metadata identity mismatch: {mismatches}")
    if set(benchmark_meta.get("adcp_roles_seen", [])) != {"architect", "coder", "reviewer", "verifier"}:
        raise ValueError("ADCP Harbor metadata lost distinct role evidence")

    if EXPECTED_FILE not in patch or "+" + EXPECTED_CONTENT not in patch:
        raise ValueError("baseline-to-final patch omitted the committed ADCP candidate")
    patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if benchmark_meta.get("patch_sha256") != patch_digest:
        raise ValueError("ADCP metadata patch digest differs from PATCH.diff")
    if benchmark_meta.get("baseline_head") == benchmark_meta.get("final_head"):
        raise ValueError("ADCP transport did not preserve evidence that candidate HEAD advanced")
    if context.get("n_input_tokens") != 0 or context.get("n_output_tokens") != 0 or context.get("n_cache_tokens") != 0:
        raise ValueError("no-model ADCP transport populated nonzero Harbor model tokens")
    if context.get("cost_usd") != 0.0:
        raise ValueError("no-model ADCP transport populated nonzero Harbor model cost")

    require_no_secret(args.trials_dir)

    evidence = {
        "scope": "PHASE3_ADCP_HARBOR_TRANSPORT_NO_MODEL",
        "status": "PASS",
        "paid_model_called": False,
        "private_runtime_executed": False,
        "runtime_identity_attested": True,
        "committed_candidate_exported": True,
        "model_route": SHARED_MODEL_ROUTE,
        "model_accounting": runtime.model_accounting.as_dict(),
        "runtime": runtime.as_metadata(),
        "patch_sha256": patch_digest,
        "patch_bytes": len(patch.encode("utf-8")),
        "verifier_result": result.get("verifier_result"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 3 ADCP Harbor transport: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
