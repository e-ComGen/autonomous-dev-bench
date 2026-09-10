"""Run the stock DeepSeek Harness inside a benchmark task environment."""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
from urllib.request import urlopen

from deepseek_harness import DeepSeekHarness
from deepseek_harness_runtime import bundled_runtime_path


REASONING_EFFORT = "high"


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def optional_usage() -> dict[str, object] | None:
    url = os.environ.get("AUTOBENCH_DEEPSEEK_USAGE_URL")
    if not url:
        return None
    with urlopen(url, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("usage endpoint returned a non-object")
    return payload


def main() -> int:
    prompt_path = Path(required_env("AUTOBENCH_DSH_PROMPT_PATH"))
    result_path = Path(required_env("AUTOBENCH_DSH_RESULT_PATH"))
    workspace = Path(os.environ.get("AUTOBENCH_DSH_WORKSPACE", "/workspace")).resolve()
    profile = os.environ.get("AUTOBENCH_DSH_PROFILE", "sdk")
    provider = os.environ.get("AUTOBENCH_DSH_PROVIDER", "deepseek-official")
    model = os.environ.get("AUTOBENCH_DSH_MODEL", "deepseek-v4-flash")
    session_id = os.environ.get("AUTOBENCH_DSH_SESSION_ID", "autobench-stock")
    max_tokens = int(os.environ.get("AUTOBENCH_DSH_MAX_TOKENS", "2048"))
    prompt = prompt_path.read_text(encoding="utf-8")
    dsh_home = Path(os.environ.get("AUTOBENCH_DSH_HOME", f"/tmp/autobench-dsh-{session_id}"))
    dsh_home.mkdir(parents=True, exist_ok=True)

    with DeepSeekHarness(
        provider=provider,
        model=model,
        reasoning_effort=REASONING_EFFORT,
        cwd=str(workspace),
        dsh_home=str(dsh_home),
        profile=profile,
        env={
            "DSH_PERMISSION_MODE": "danger-full-access",
            "DSH_TELEMETRY_DISABLED": "1",
            "DSH_SESSION_STORE": "jsonl",
        },
        api_key=required_env("DEEPSEEK_API_KEY"),
        base_url=required_env("DEEPSEEK_BASE_URL"),
        max_tokens=max_tokens,
        request_timeout_seconds=90,
    ) as harness:
        result = harness.run(prompt, session_id=session_id)

    payload = {
        "sdk_version": importlib.metadata.version("deepseek-harness-sdk"),
        "runtime_version": importlib.metadata.version("deepseek-harness-runtime-bin"),
        "runtime_path": str(bundled_runtime_path().resolve()),
        "profile": profile,
        "provider": provider,
        "model": model,
        "reasoning_effort": REASONING_EFFORT,
        "session_id": result.session_id,
        "finish_reason": result.finish_reason,
        "final_response": result.final_response,
        "event_count": len(result.events),
        "event_types": [event.get("type") for event in result.events if isinstance(event, dict)],
        "usage": optional_usage(),
        "fake_model": os.environ.get("AUTOBENCH_FAKE_MODEL") == "1",
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
