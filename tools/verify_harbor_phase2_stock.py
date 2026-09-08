"""Validate StockDeepSeekAgent transport through Harbor without a paid model call."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FAKE_SECRET = b"PHASE2_FAKE_KEY_DO_NOT_PERSIST"
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
        raise ValueError(f"stock verifier did not return full reward: {rewards!r}")


def require_no_secret(root: Path) -> None:
    leaked: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if FAKE_SECRET in payload:
            leaked.append(str(path.relative_to(root)))
    if leaked:
        raise ValueError(f"controller API key leaked into Harbor trial artifacts: {leaked}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--dsh-lock", type=Path, default=Path("DEEPSEEK_HARNESS.lock.json"))
    parser.add_argument("--wheel-manifest", type=Path, default=Path("artifacts/harbor-phase2/DSH_WHEELS.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/harbor-phase2/PHASE2_STOCK_DEEPSEEK_TRANSPORT.json"))
    args = parser.parse_args()

    result_path = unique_file(args.trials_dir, "result.json")
    dsh_result_path = unique_file(args.trials_dir, "DSH_RESULT.json")
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    result = load_json(result_path)
    dsh_result = load_json(dsh_result_path)
    lock = load_json(args.dsh_lock)
    wheels = load_json(args.wheel_manifest)
    patch = patch_path.read_text(encoding="utf-8")

    if result.get("exception_info") is not None:
        raise ValueError(f"StockDeepSeekAgent Harbor trial failed: {result['exception_info']}")
    full_reward(result)

    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict) or agent_info.get("name") != "stock-deepseek-harness":
        raise ValueError(f"unexpected Harbor agent identity: {agent_info!r}")
    context = result.get("agent_result")
    if not isinstance(context, dict):
        raise ValueError("Harbor did not persist StockDeepSeekAgent AgentContext")
    metadata = context.get("metadata")
    benchmark_meta = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(benchmark_meta, dict) or benchmark_meta.get("agent") != "stock_deepseek_harness":
        raise ValueError("StockDeepSeekAgent benchmark metadata is missing")

    sdk = lock.get("sdk")
    runtime = lock.get("runtime")
    if not isinstance(sdk, dict) or not isinstance(runtime, dict):
        raise ValueError("DeepSeek Harness lock is malformed")
    expected_version = sdk.get("version")
    if expected_version != runtime.get("version"):
        raise ValueError("DeepSeek Harness SDK/runtime lock versions differ")
    expected_identity = {
        "sdk_version": expected_version,
        "runtime_version": expected_version,
        "profile": lock.get("profile"),
        "provider": lock.get("provider"),
        "model": lock.get("model"),
        "fake_model": True,
    }
    mismatches = {
        key: {"expected": expected, "observed": dsh_result.get(key)}
        for key, expected in expected_identity.items()
        if dsh_result.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"stock DeepSeek Harness identity mismatch: {mismatches}")
    if dsh_result.get("final_response") != "STOCK_HARNESS_FAKE_OK":
        raise ValueError(f"stock DeepSeek coding turn ended unexpectedly: {dsh_result.get('final_response')!r}")

    usage = dsh_result.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("fake provider usage was not captured by the in-environment runner")
    requests = usage.get("requests")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    cache_tokens = usage.get("cache_tokens")
    for name, value in (
        ("requests", requests),
        ("prompt_tokens", prompt_tokens),
        ("completion_tokens", completion_tokens),
        ("cache_tokens", cache_tokens),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid fake-provider usage {name}: {value!r}")
    if requests < 2:
        raise ValueError(f"stock coding turn made too few provider requests: {requests}")
    if usage.get("tool_call_requests") != 1 or usage.get("tool_result_requests") != 1:
        raise ValueError(f"stock harness did not execute exactly one coding tool cycle: {usage}")
    auxiliary = usage.get("auxiliary_requests")
    if isinstance(auxiliary, bool) or not isinstance(auxiliary, int) or auxiliary < 0:
        raise ValueError(f"invalid auxiliary request count: {auxiliary!r}")
    if 1 + 1 + auxiliary != requests:
        raise ValueError(f"provider request taxonomy does not account for all calls: {usage}")
    advertised = usage.get("advertised_tools")
    if not isinstance(advertised, list) or "write" not in advertised:
        raise ValueError(f"release SDK profile did not advertise its write tool: {advertised!r}")

    expected_context = {
        "n_input_tokens": prompt_tokens,
        "n_output_tokens": completion_tokens,
        "n_cache_tokens": cache_tokens,
        "cost_usd": 0.0,
    }
    for key, expected in expected_context.items():
        if context.get(key) != expected:
            raise ValueError(f"Harbor AgentContext {key} != provider usage: {context.get(key)!r} != {expected!r}")
    if benchmark_meta.get("fake_model") is not True:
        raise ValueError("StockDeepSeekAgent did not mark the qualification route as fake")

    if EXPECTED_FILE not in patch or "new file mode" not in patch or f"+{EXPECTED_CONTENT}" not in patch:
        raise ValueError("StockDeepSeekAgent patch export omitted the new untracked file")
    patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if benchmark_meta.get("patch_sha256") != patch_digest:
        raise ValueError("Harbor metadata patch digest does not match exported PATCH.diff")

    wheel_entries = wheels.get("wheels")
    if not isinstance(wheel_entries, list) or not wheel_entries:
        raise ValueError("DSH wheel closure manifest is empty")
    wheel_by_name = {
        entry.get("filename"): entry.get("sha256")
        for entry in wheel_entries
        if isinstance(entry, dict) and isinstance(entry.get("filename"), str)
    }
    expected_wheels = {
        sdk.get("wheel"): sdk.get("sha256"),
        runtime.get("linux_x86_64_wheel"): runtime.get("linux_x86_64_sha256"),
    }
    for filename, digest in expected_wheels.items():
        if wheel_by_name.get(filename) != digest:
            raise ValueError(f"pinned DeepSeek Harness wheel missing or changed: {filename}")

    require_no_secret(args.trials_dir)

    evidence = {
        "scope": "PHASE2_STOCK_DEEPSEEK_TRANSPORT_FAKE_MODEL",
        "status": "PASS",
        "paid_model_called": False,
        "fake_model_called": True,
        "deepseek_harness": lock,
        "wheel_closure": wheels,
        "provider_usage": usage,
        "harbor_agent_context": {
            key: context.get(key) for key in ("n_input_tokens", "n_cache_tokens", "n_output_tokens", "cost_usd")
        },
        "agent_metadata": benchmark_meta,
        "patch_sha256": patch_digest,
        "patch_bytes": len(patch.encode("utf-8")),
        "verifier_result": result.get("verifier_result"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Harbor StockDeepSeekAgent transport: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
