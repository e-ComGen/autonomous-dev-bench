from __future__ import annotations

import argparse
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path

from benchmark_core.deepseek_v4_estimator import DeepSeekV4RequestEstimator


"""Verify a later authenticated provider capture without making a model call.

The production estimator intentionally reserves the full pinned DeepSeek-V4
reference prompt. For thinking requests that reference prompt contains an
explicit reasoning-effort control prefix. The official API receives effort as a
separate wire parameter and its ``usage.prompt_tokens`` accounts the user prompt,
not that local reference-only control prefix.

Therefore live qualification has two simultaneous obligations:

* exact provider-accounted prompt parity: render the same request with the
  reference encoder's no-op ``low`` effort prefix and require that token count to
  equal the official provider ``prompt_tokens``;
* admission safety: the full reference-prompt reservation must never be smaller
  than provider-reported input usage.

The verifier never reads an API key and never contacts DeepSeek.
"""


def _provider_accounted_request(request: dict[str, object]) -> dict[str, object]:
    """Remove only the reference encoder's textual effort-control prefix.

    DeepSeek's pinned V4 encoder defines ``low`` as an empty effort prefix. The
    actual message/tool context remains byte-for-byte the same. This is not a
    heuristic token subtraction and does not hard-code the observed 53-token
    difference from qualification.
    """
    adjusted = deepcopy(request)
    thinking = adjusted.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        adjusted["reasoning_effort"] = "low"
    return adjusted


def _estimate_without_console_noise(request: dict[str, object], cache_dir: Path):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
            cache_dir=cache_dir,
            allow_network=False,
        )
        return estimator.estimate(request)


def _estimate_both_without_console_noise(
    request: dict[str, object], cache_dir: Path
):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
            cache_dir=cache_dir,
            allow_network=False,
        )
        reference_envelope = estimator.estimate(request)
        provider_accounted = estimator.estimate(_provider_accounted_request(request))
    return reference_envelope, provider_accounted


def verify_capture(capture: dict[str, object], cache_dir: Path) -> dict[str, object]:
    if capture.get("model_called") is not True:
        raise ValueError("capture must describe a real provider call")
    if capture.get("provider") != "deepseek-official":
        raise ValueError("capture provider must be deepseek-official")
    request = capture.get("request")
    usage = capture.get("usage")
    if not isinstance(request, dict) or not isinstance(usage, dict):
        raise ValueError("capture requires request and usage objects")
    prompt_tokens = usage.get("prompt_tokens")
    if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
        raise ValueError("capture usage requires non-negative prompt_tokens")

    reference, provider_accounted = _estimate_both_without_console_noise(request, cache_dir)
    exact_match = provider_accounted.input_tokens == prompt_tokens
    non_underestimate = reference.input_tokens >= prompt_tokens
    effort_prefix_tokens = reference.input_tokens - provider_accounted.input_tokens

    thinking = request.get("thinking")
    requested_effort = request.get("reasoning_effort")
    explicit_effort_prefix_expected = (
        isinstance(thinking, dict)
        and thinking.get("type") == "enabled"
        and requested_effort in {"high", "max"}
    )
    effort_structure_ok = (
        effort_prefix_tokens > 0 if explicit_effort_prefix_expected else effort_prefix_tokens == 0
    )

    passed = exact_match and non_underestimate and effort_structure_ok
    return {
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_PARITY",
        "status": "PASS" if passed else "FAIL",
        "provider_accounted_input_tokens": provider_accounted.input_tokens,
        "reference_envelope_input_tokens": reference.input_tokens,
        "provider_prompt_tokens": prompt_tokens,
        "reference_effort_prefix_tokens": effort_prefix_tokens,
        "exact_match": exact_match,
        "reference_envelope_non_underestimate": non_underestimate,
        "effort_prefix_structure_ok": effort_structure_ok,
        "provider": capture["provider"],
        "model_called": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()

    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    if not isinstance(capture, dict):
        raise SystemExit("capture must contain a JSON object")
    try:
        result = verify_capture(capture, args.cache_dir)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
