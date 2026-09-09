from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODEL = "deepseek-v4-flash"
PROVIDER = "deepseek-official"


def parity_request(*, text: str, max_tokens: int) -> dict[str, object]:
    if not text.strip():
        raise ValueError("parity text must be non-empty")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    return {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": text},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": max_tokens,
    }


def capture(
    request_body: dict[str, object],
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: int = 90,
) -> dict[str, object]:
    if not api_key.strip():
        raise ValueError("DeepSeek API key is empty")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(request_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "autonomous-dev-bench/deepseek-v4-usage-parity",
        },
    )

    usage: dict[str, object] | None = None
    provider_request_id: str | None = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            provider_request_id = response.headers.get("x-request-id") or response.headers.get(
                "x-deepseek-request-id"
            )
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                if not isinstance(chunk, dict):
                    raise ValueError("DeepSeek SSE chunk is not an object")
                candidate = chunk.get("usage")
                if candidate is not None:
                    if not isinstance(candidate, dict):
                        raise ValueError("DeepSeek SSE usage is not an object")
                    usage = candidate
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[-2000:]
        raise RuntimeError(f"DeepSeek parity request failed with HTTP {error.code}: {detail}") from error

    if usage is None:
        raise RuntimeError("DeepSeek stream completed without terminal usage")
    prompt_tokens = usage.get("prompt_tokens")
    if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
        raise RuntimeError("DeepSeek terminal usage has invalid prompt_tokens")

    return {
        "schema_version": 1,
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_CAPTURE",
        "request": request_body,
        "usage": usage,
        "model_called": True,
        "provider": PROVIDER,
        "model": MODEL,
        "provider_request_id": provider_request_id,
        "credential_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key-env", default="AUTOBENCH_DEEPSEEK_API_KEY")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--text", default="Reply with OK.")
    parser.add_argument("--max-tokens", type=int, default=8)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key.strip():
        raise SystemExit(f"required credential environment variable is missing: {args.api_key_env}")

    result = capture(
        parity_request(text=args.text, max_tokens=args.max_tokens),
        api_key=api_key,
        base_url=args.base_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"captured provider prompt_tokens={result['usage']['prompt_tokens']}")
    print(f"evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
