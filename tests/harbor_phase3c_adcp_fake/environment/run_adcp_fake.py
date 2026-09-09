from __future__ import annotations

import json
import os
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise SystemExit(f"missing {name}")
    return value


def main() -> int:
    if os.environ.get("AUTOBENCH_ADCP_FAKE_RUNTIME") != "1":
        raise SystemExit("fake qualification runner requires explicit fake-runtime mode")
    workspace = Path(required("AUTOBENCH_ADCP_WORKSPACE")).resolve()
    instruction = Path(required("AUTOBENCH_ADCP_INSTRUCTION_PATH")).read_text(encoding="utf-8")
    result_path = Path(required("AUTOBENCH_ADCP_RESULT_PATH"))
    if not instruction.strip():
        raise SystemExit("instruction is empty")

    proxy_url = required("DEEPSEEK_BASE_URL")
    proxy_token = required("DEEPSEEK_API_KEY")
    if os.environ.get("AUTOBENCH_MODEL_PROXY_MODE") != "1":
        raise SystemExit("budget proxy mode was not asserted")

    # Simulate the observable state transition only. This runner does not import
    # or claim to execute the private ADCP runtime and makes no model call.
    target = workspace / "message.txt"
    target.write_text("candidate before repair\n", encoding="utf-8")
    target.write_text("adcp candidate ready after repair\n", encoding="utf-8")

    receipt = {
        "schema": "autobench.adcp-harbor-result/1",
        "target_runtime": {
            "repository": required("AUTOBENCH_ADCP_TARGET_REPOSITORY"),
            "commit": required("AUTOBENCH_ADCP_TARGET_COMMIT"),
            "runtime": required("AUTOBENCH_ADCP_TARGET_RUNTIME"),
            "integration": required("AUTOBENCH_ADCP_TARGET_INTEGRATION"),
        },
        "runtime_loaded": False,
        "fake_runtime": True,
        "role_ids": {
            "architect": "fake-local-architect",
            "coder": "fake-coder",
            "reviewer": "fake-reviewer",
            "verifier": "fake-verifier",
        },
        "role_call_counts": {
            "architect": 1,
            "coder": 2,
            "reviewer": 2,
            "verifier": 2,
        },
        "event_sequence": [
            "ARCHITECT",
            "CODER",
            "REVIEWER",
            "VERIFIER",
            "BADC_REPAIR",
            "CODER",
            "REVIEWER",
            "VERIFIER",
            "CANDIDATE_READY",
        ],
        "outcome_status": "CANDIDATE_READY",
        "candidate_ready": True,
        "task_completed": False,
        "model_route": required("AUTOBENCH_ADCP_MODEL"),
        "provider_route": required("AUTOBENCH_ADCP_PROVIDER"),
        "model_calls_via_budget_proxy": bool(proxy_url and proxy_token),
        "upstream_provider_credential_present": bool(
            os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY")
        ),
        "proxy_credential_present": bool(proxy_token),
        "model_called": False,
        "session_id": "phase3c-fake-session",
        "request_id": "phase3c-fake-request",
        "candidate_snapshot_id": "phase3c-candidate-after-repair",
        "repair_count": 1,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
