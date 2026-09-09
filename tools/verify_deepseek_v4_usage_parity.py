from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.deepseek_v4_estimator import DeepSeekV4RequestEstimator


"""Verify a later authenticated provider capture without making a model call.

Input JSON schema:
{
  "request": <exact chat-completions wire object>,
  "usage": {"prompt_tokens": <provider integer>, ...},
  "model_called": true,
  "provider": "deepseek-official"
}

This verifier deliberately consumes evidence produced elsewhere. It never reads
an API key, never contacts DeepSeek, and never promotes offline qualification to
paid readiness by itself.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()

    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    if capture.get("model_called") is not True:
        raise SystemExit("capture must describe a real provider call")
    if capture.get("provider") != "deepseek-official":
        raise SystemExit("capture provider must be deepseek-official")
    request = capture.get("request")
    usage = capture.get("usage")
    if not isinstance(request, dict) or not isinstance(usage, dict):
        raise SystemExit("capture requires request and usage objects")
    prompt_tokens = usage.get("prompt_tokens")
    if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
        raise SystemExit("capture usage requires non-negative prompt_tokens")

    estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
        cache_dir=args.cache_dir,
        allow_network=False,
    )
    estimated = estimator.estimate(request)
    result = {
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_PARITY",
        "status": "PASS" if estimated.input_tokens == prompt_tokens else "FAIL",
        "estimated_input_tokens": estimated.input_tokens,
        "provider_prompt_tokens": prompt_tokens,
        "exact_match": estimated.input_tokens == prompt_tokens,
        "provider": capture["provider"],
        "model_called": True,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["exact_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
