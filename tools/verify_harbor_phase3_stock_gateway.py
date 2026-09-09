"""Validate Stock DeepSeek Harness through the shared budget gateway with no paid model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


GATEWAY_TOKEN = b"PHASE3_STOCK_GATEWAY_TOKEN_DO_NOT_PERSIST"
UPSTREAM_KEY = b"PHASE3_STOCK_UPSTREAM_KEY_DO_NOT_PERSIST"
EXPECTED_FILE = "stock-harness.txt"
EXPECTED_CONTENT = "created by stock deepseek harness"


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def full_reward(result: dict[str, object]) -> None:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"stock shared-gateway verifier did not return full reward: {rewards!r}")


def require_no_secrets(root: Path) -> None:
    leaked: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if GATEWAY_TOKEN in payload or UPSTREAM_KEY in payload:
            leaked.append(str(path.relative_to(root)))
    if leaked:
        raise ValueError(f"model-route credential leaked into Harbor trial artifacts: {leaked}")


def valid_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--dsh-lock", type=Path, default=Path("DEEPSEEK_HARNESS.lock.json"))
    parser.add_argument("--wheel-manifest", type=Path, default=Path("artifacts/harbor-phase3/DSH_WHEELS.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/harbor-phase3/PHASE3_STOCK_SHARED_GATEWAY.json"),
    )
    args = parser.parse_args()

    result = load_json(unique_file(args.trials_dir, "result.json"))
    dsh_result = load_json(unique_file(args.trials_dir, "DSH_RESULT.json"))
    patch = unique_file(args.trials_dir, "PATCH.diff").read_text(encoding="utf-8")
    lock = load_json(args.dsh_lock)
    wheels = load_json(args.wheel_manifest)

    if result.get("exception_info") is not None:
        raise ValueError(f"StockDeepSeekAgent Harbor trial failed: {result['exception_info']}")
    full_reward(result)

    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict) or agent_info.get("name") != "stock-deepseek-harness":
        raise ValueError(f"unexpected Harbor agent identity: {agent_info!r}")
    context = result.get("agent_result")
    if not isinstance(context, dict):
        raise ValueError("Harbor did not persist StockDeepSeekAgent context")
    metadata = context.get("metadata")
    benchmark_meta = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(benchmark_meta, dict):
        raise ValueError("Stock shared-gateway metadata missing")

    sdk = lock.get("sdk")
    runtime = lock.get("runtime")
    if not isinstance(sdk, dict) or not isinstance(runtime, dict):
        raise ValueError("DeepSeek Harness lock malformed")
    expected_version = sdk.get("version")
    expected_identity = {
        "sdk_version": expected_version,
        "runtime_version": expected_version,
        "profile": lock.get("profile"),
        "provider": lock.get("provider"),
        "model": lock.get("model"),
        "fake_model": False,
        "model_route": "shared_budget_gateway",
        "direct_model_api_used": False,
    }
    mismatches = {
        key: {"expected": expected, "observed": dsh_result.get(key)}
        for key, expected in expected_identity.items()
        if dsh_result.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"stock shared-gateway identity mismatch: {mismatches}")
    if dsh_result.get("final_response") != "STOCK_SHARED_GATEWAY_OK":
        raise ValueError(f"stock shared-gateway coding turn ended unexpectedly: {dsh_result.get('final_response')!r}")

    usage = dsh_result.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("shared gateway usage snapshot missing from stock runner")
    if usage.get("model") != lock.get("model") or usage.get("model_route") != "shared_budget_gateway":
        raise ValueError(f"gateway usage identity mismatch: {usage}")
    if usage.get("streaming_mode") != "buffered_sse_usage_accounted":
        raise ValueError(f"stock route did not use qualified SSE gateway mode: {usage.get('streaming_mode')!r}")
    if usage.get("accounting_valid") is not True or usage.get("violations") != []:
        raise ValueError(f"stock gateway accounting invalid or violated: {usage}")

    requests = valid_count(usage.get("requests"), "gateway request count")
    input_tokens = valid_count(usage.get("input_tokens"), "gateway input tokens")
    output_tokens = valid_count(usage.get("output_tokens"), "gateway output tokens")
    cache_tokens = valid_count(usage.get("cache_tokens"), "gateway cache tokens")
    reasoning_tokens = valid_count(usage.get("reasoning_tokens"), "gateway reasoning tokens")
    cost_micros = valid_count(usage.get("cost_usd_micros"), "gateway cost micros")
    if requests < 2:
        raise ValueError(f"stock coding cycle made too few shared-gateway requests: {requests}")
    if input_tokens != requests * 3 or output_tokens != requests * 3:
        raise ValueError(f"deterministic SSE usage does not account for every stock request: {usage}")
    if usage.get("total_model_tokens") != input_tokens + output_tokens:
        raise ValueError("gateway primary total differs from input+output")
    if cache_tokens != 0 or reasoning_tokens != 0 or cost_micros != 0:
        raise ValueError(f"deterministic stock gateway diagnostics changed unexpectedly: {usage}")

    expected_context = {
        "n_input_tokens": input_tokens,
        "n_output_tokens": output_tokens,
        "n_cache_tokens": cache_tokens,
        "cost_usd": 0.0,
    }
    for key, expected in expected_context.items():
        if context.get(key) != expected:
            raise ValueError(f"Harbor AgentContext {key} != shared gateway usage: {context.get(key)!r} != {expected!r}")

    expected_meta = {
        "fake_model": False,
        "model_route": "shared_budget_gateway",
        "direct_model_api_used": False,
        "model_accounting_valid": True,
        "model_budget_violations": [],
        "model_requests": requests,
    }
    for key, expected in expected_meta.items():
        if benchmark_meta.get(key) != expected:
            raise ValueError(f"Stock metadata {key} mismatch: {benchmark_meta.get(key)!r} != {expected!r}")

    if EXPECTED_FILE not in patch or "new file mode" not in patch or f"+{EXPECTED_CONTENT}" not in patch:
        raise ValueError("Stock shared-gateway patch omitted the coding result")
    patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if benchmark_meta.get("patch_sha256") != patch_digest:
        raise ValueError("Stock metadata patch digest differs from PATCH.diff")

    wheel_entries = wheels.get("wheels")
    if not isinstance(wheel_entries, list) or not wheel_entries:
        raise ValueError("DSH wheel closure manifest empty")
    wheel_by_name = {
        entry.get("filename"): entry.get("sha256")
        for entry in wheel_entries
        if isinstance(entry, dict) and isinstance(entry.get("filename"), str)
    }
    for filename, digest in {
        sdk.get("wheel"): sdk.get("sha256"),
        runtime.get("linux_x86_64_wheel"): runtime.get("linux_x86_64_sha256"),
    }.items():
        if wheel_by_name.get(filename) != digest:
            raise ValueError(f"pinned DeepSeek Harness wheel missing or changed: {filename}")

    require_no_secrets(args.trials_dir)

    evidence = {
        "scope": "PHASE3_STOCK_DEEPSEEK_SHARED_MODEL_GATEWAY_FAKE_UPSTREAM",
        "status": "PASS",
        "paid_model_called": False,
        "deterministic_fake_upstream": True,
        "stock_direct_model_api_used": False,
        "model_route": "shared_budget_gateway",
        "streaming_mode": "buffered_sse_usage_accounted",
        "deepseek_harness": lock,
        "model_accounting": usage,
        "patch_sha256": patch_digest,
        "patch_bytes": len(patch.encode("utf-8")),
        "verifier_result": result.get("verifier_result"),
    }
    serialized = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if GATEWAY_TOKEN.decode() in serialized or UPSTREAM_KEY.decode() in serialized:
        raise ValueError("stock gateway evidence leaked a qualification credential")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(f"Phase 3 Stock shared-gateway transport: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
