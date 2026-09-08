"""Validate Harbor timeout, network, and resource lifecycle probes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def load_json(root: Path, name: str) -> dict[str, object]:
    payload = json.loads(unique_file(root, name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain an object")
    return payload


def full_reward(result: dict[str, object], label: str) -> None:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(value) for value in rewards.values()) != 1.0:
        raise ValueError(f"{label} verifier did not return full reward: {rewards!r}")


def require_zero_model_usage(result: dict[str, object], label: str) -> None:
    context = result.get("agent_result")
    if not isinstance(context, dict):
        raise ValueError(f"{label} did not persist AgentContext")
    expected = {
        "n_input_tokens": 0,
        "n_cache_tokens": 0,
        "n_output_tokens": 0,
        "cost_usd": 0.0,
    }
    for key, value in expected.items():
        if context.get(key) != value:
            raise ValueError(f"{label} {key} mismatch: {context.get(key)!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-dir", type=Path, required=True)
    parser.add_argument("--network-dir", type=Path, required=True)
    parser.add_argument("--resource-dir", type=Path, required=True)
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/harbor-phase2/PHASE2_HARBOR_LIFECYCLE.json"))
    args = parser.parse_args()

    timeout_result = load_json(args.timeout_dir, "result.json")
    timeout_exception = timeout_result.get("exception_info")
    if not isinstance(timeout_exception, dict) or timeout_exception.get("exception_type") != "AgentTimeoutError":
        raise ValueError(f"timeout trial did not fail with AgentTimeoutError: {timeout_exception!r}")
    if timeout_result.get("verifier_result") is not None:
        raise ValueError("timeout trial unexpectedly reached final verification")

    network_result = load_json(args.network_dir, "result.json")
    if network_result.get("exception_info") is not None:
        raise ValueError(f"network trial failed: {network_result['exception_info']}")
    full_reward(network_result, "network")
    require_zero_model_usage(network_result, "network")
    network_probe = load_json(args.network_dir, "NETWORK_PROBE.json")
    if network_probe.get("model_called") is not False:
        raise ValueError("network probe unexpectedly called a model")
    egress_code = network_probe.get("egress_return_code")
    if isinstance(egress_code, bool) or not isinstance(egress_code, int) or egress_code == 0:
        raise ValueError(f"no-network probe did not deny public HTTPS: {egress_code!r}")

    resource_result = load_json(args.resource_dir, "result.json")
    if resource_result.get("exception_info") is not None:
        raise ValueError(f"resource trial failed: {resource_result['exception_info']}")
    full_reward(resource_result, "resource")
    require_zero_model_usage(resource_result, "resource")
    resource_probe = load_json(args.resource_dir, "RESOURCE_PROBE.json")
    if resource_probe.get("memory_max") != "268435456":
        raise ValueError(f"memory limit was not enforced: {resource_probe.get('memory_max')!r}")
    cpu_max = resource_probe.get("cpu_max")
    if not isinstance(cpu_max, str):
        raise ValueError("resource probe has no cpu.max")
    parts = cpu_max.split()
    if len(parts) != 2 or parts[0] == "max":
        raise ValueError(f"CPU limit was not enforced: {cpu_max!r}")
    quota, period = (int(part) for part in parts)
    if quota <= 0 or period <= 0 or quota > period:
        raise ValueError(f"CPU quota exceeds one CPU: {cpu_max!r}")

    lock = json.loads(args.harbor_lock.read_text(encoding="utf-8"))
    evidence = {
        "scope": "PHASE2_HARBOR_LIFECYCLE_NO_MODEL",
        "status": "PASS",
        "model_called": False,
        "harbor": lock,
        "timeout": {
            "exception_type": timeout_exception["exception_type"],
            "exception_message": timeout_exception.get("exception_message"),
        },
        "network": network_probe,
        "resources": resource_probe,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Harbor Phase 2 lifecycle: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
