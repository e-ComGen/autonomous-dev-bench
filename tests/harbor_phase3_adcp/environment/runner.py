"""No-model transport stub for qualifying the public Harbor ADCP adapter.

This is not an implementation of ADCP. It only attests the exact external
runtime identity, creates one deterministic committed candidate, and emits the
same result envelope expected from the private runtime integration runner.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


EXPECTED = {
    "AUTOBENCH_ADCP_RUNTIME_REPOSITORY": "e-ComGen/autonomous-dev-control-plane",
    "AUTOBENCH_ADCP_RUNTIME_COMMIT": "285702063815280398b95ba8696566259c8b5b34",
    "AUTOBENCH_ADCP_RUNTIME_ENTRYPOINT": "packages.zone_development.assured_runtime.ZoneDevelopmentRuntime",
    "AUTOBENCH_ADCP_INTEGRATION": "existing-v2-runtime-role-ports",
    "AUTOBENCH_MODEL_ROUTE": "shared_budget_gateway",
}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable {name}")
    return value


def git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    for name, expected in EXPECTED.items():
        observed = required_env(name)
        if observed != expected:
            raise ValueError(f"{name} mismatch: {observed!r} != {expected!r}")
    required_env("AUTOBENCH_MODEL_GATEWAY_URL")
    required_env("AUTOBENCH_MODEL_GATEWAY_TOKEN")
    required_env("AUTOBENCH_MODEL_GATEWAY_USAGE_URL")
    required_env("AUTOBENCH_ADCP_MODEL")

    workspace = args.workspace.resolve(strict=True)
    instruction = args.instruction.read_text(encoding="utf-8")
    if not instruction.strip():
        raise ValueError("instruction is empty")

    before = git(workspace, "rev-parse", "HEAD")
    marker = workspace / "adcp-candidate.txt"
    marker.write_text("committed by phase3 ADCP transport stub\n", encoding="utf-8")
    git(workspace, "add", "adcp-candidate.txt")
    git(
        workspace,
        "-c", "user.name=ADCP Transport Stub",
        "-c", "user.email=adcp-stub@example.invalid",
        "commit", "-m", "Phase 3 committed candidate transport",
    )
    after = git(workspace, "rev-parse", "HEAD")
    if after == before:
        raise ValueError("candidate commit did not advance HEAD")

    payload = {
        "runtime_repository": EXPECTED["AUTOBENCH_ADCP_RUNTIME_REPOSITORY"],
        "runtime_commit": EXPECTED["AUTOBENCH_ADCP_RUNTIME_COMMIT"],
        "runtime_entrypoint": EXPECTED["AUTOBENCH_ADCP_RUNTIME_ENTRYPOINT"],
        "integration": EXPECTED["AUTOBENCH_ADCP_INTEGRATION"],
        "model_route": EXPECTED["AUTOBENCH_MODEL_ROUTE"],
        "direct_model_api_used": False,
        "outcome": "CANDIDATE_READY",
        "role_calls": 4,
        "roles_seen": ["architect", "coder", "reviewer", "verifier"],
        "evidence": ["transport:committed-candidate"],
        "model_accounting": {
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_tokens": 0,
            "cost_usd_micros": 0,
            "accounting_valid": True,
            "violations": [],
        },
        "metadata": {
            "qualification_stub": True,
            "paid_model_called": False,
            "baseline_head": before,
            "candidate_head": after,
        },
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
