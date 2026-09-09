"""Validate a real Harbor trial executed through the Daytona remote provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_AGENT = "autobench-harbor-daytona-remote-probe"
EXPECTED_PROVIDER = "daytona"
EXPECTED_OS = "Linux"


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def require_full_reward(result: dict[str, object]) -> dict[str, object]:
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or not rewards or max(float(v) for v in rewards.values()) != 1.0:
        raise ValueError(f"Daytona Harbor verifier did not return full reward: {rewards!r}")
    return verifier


def require_secret_not_persisted(root: Path, env_name: str) -> None:
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"required controller credential is absent or empty: {env_name}")
    needle = value.encode("utf-8")
    leaked: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if needle in path.read_bytes():
                leaked.append(str(path.relative_to(root)))
        except OSError:
            continue
    if leaked:
        raise ValueError(f"Daytona controller credential leaked into trial artifacts: {leaked}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--harbor-lock", type=Path, default=Path("HARBOR.lock.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/harbor-phase2/PHASE2_DAYTONA_REMOTE_PROVIDER.json"),
    )
    args = parser.parse_args()

    lock = load_object(args.harbor_lock)
    providers = lock.get("remote_providers")
    provider_lock = providers.get(EXPECTED_PROVIDER) if isinstance(providers, dict) else None
    if not isinstance(provider_lock, dict):
        raise ValueError("HARBOR.lock.json does not pin the Daytona provider")
    credential_env = provider_lock.get("credential_env")
    if not isinstance(credential_env, str) or not credential_env:
        raise ValueError("Daytona credential environment name is not pinned")

    result = load_object(unique_file(args.trials_dir, "result.json"))
    probe = load_object(unique_file(args.trials_dir, "PROBE.json"))
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    patch = patch_path.read_text(encoding="utf-8")

    if result.get("exception_info") is not None:
        raise ValueError(f"Daytona Harbor trial failed: {result['exception_info']}")
    verifier = require_full_reward(result)

    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict) or agent_info.get("name") != EXPECTED_AGENT:
        raise ValueError(f"unexpected Harbor agent identity: {agent_info!r}")

    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        raise ValueError("Harbor did not persist AgentContext for Daytona trial")
    for key, expected in (
        ("n_input_tokens", 0),
        ("n_cache_tokens", 0),
        ("n_output_tokens", 0),
        ("cost_usd", 0.0),
    ):
        if agent_result.get(key) != expected:
            raise ValueError(f"Daytona AgentContext {key} mismatch: {agent_result.get(key)!r}")

    metadata = agent_result.get("metadata")
    benchmark_meta = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(benchmark_meta, dict):
        raise ValueError("Daytona benchmark metadata missing from AgentContext")

    required_probe = {
        "remote_provider": EXPECTED_PROVIDER,
        "environment_type": EXPECTED_PROVIDER,
        "sandbox_id_present": True,
        "os": EXPECTED_OS,
        "model_called": False,
    }
    for key, expected in required_probe.items():
        if probe.get(key) != expected:
            raise ValueError(f"Daytona probe {key} mismatch: {probe.get(key)!r} != {expected!r}")
        if benchmark_meta.get(key) != expected:
            raise ValueError(f"Daytona AgentContext metadata {key} mismatch")

    environment_class = probe.get("environment_class")
    if not isinstance(environment_class, str) or "daytona" not in environment_class.lower():
        raise ValueError(f"unexpected Daytona environment class: {environment_class!r}")
    sandbox_digest = probe.get("sandbox_id_sha256")
    if not isinstance(sandbox_digest, str) or len(sandbox_digest) != 64:
        raise ValueError("Daytona sandbox id digest is missing or malformed")
    architecture = probe.get("architecture")
    if not isinstance(architecture, str) or not architecture:
        raise ValueError("Daytona architecture evidence is missing")

    if "-baseline" not in patch or "+harbor substrate qualified" not in patch:
        raise ValueError("Daytona patch transport omitted the expected workspace mutation")
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()

    require_secret_not_persisted(args.trials_dir, credential_env)

    evidence = {
        "scope": "PHASE2_HARBOR_REMOTE_PROVIDER_DAYTONA",
        "status": "PASS",
        "model_called": False,
        "paid_model_called": False,
        "provider": EXPECTED_PROVIDER,
        "harbor": lock,
        "provider_lock": provider_lock,
        "remote_execution": {
            "environment_type": probe["environment_type"],
            "environment_class": environment_class,
            "sandbox_id_present": True,
            "sandbox_id_sha256": sandbox_digest,
            "os": probe["os"],
            "architecture": architecture,
        },
        "credential_boundary": {
            "controller_env": credential_env,
            "persisted_in_trial_artifacts": False,
        },
        "patch_sha256": patch_sha256,
        "patch_bytes": len(patch.encode("utf-8")),
        "verifier_result": verifier,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Harbor Daytona remote provider: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
