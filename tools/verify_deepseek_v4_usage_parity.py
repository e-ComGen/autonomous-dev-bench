from __future__ import annotations

import argparse
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path

from benchmark_core.deepseek_v4_estimator import DeepSeekV4RequestEstimator


"""Verify hosted DeepSeek usage against the pinned local reservation model.

DeepSeek response ``usage`` is the source of truth for actual processed tokens.
The pinned open-weight V4 reference encoder remains the deterministic
pre-dispatch reservation model. For the locked high-effort qualification probe,
we render the request twice:

* ``low`` removes only the reference encoder's textual reasoning-effort prefix;
* ``high`` is the full production reservation envelope used before dispatch.

Qualification records both an exact fixed-probe parity signal and a conservative
coverage signal. The readiness gate may require exact parity for this one frozen
probe, while paid execution continues to reserve the full high-effort envelope
and commits actual provider usage afterwards. No observed token delta is
hard-coded. This verifier never reads an API key and never contacts DeepSeek.
"""

LOCKED_REASONING_EFFORT = "high"
LOCKED_MODEL = "deepseek-v4-flash"


def _no_effort_prefix_request(request: dict[str, object]) -> dict[str, object]:
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


def _estimate_bounds_without_console_noise(
    request: dict[str, object], cache_dir: Path
):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
            cache_dir=cache_dir,
            allow_network=False,
        )
        reference_envelope = estimator.estimate(request)
        no_effort_prefix = estimator.estimate(_no_effort_prefix_request(request))
    return reference_envelope, no_effort_prefix


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

    thinking = request.get("thinking")
    request_policy_matches = (
        request.get("model") == LOCKED_MODEL
        and isinstance(thinking, dict)
        and thinking.get("type") == "enabled"
        and request.get("reasoning_effort") == LOCKED_REASONING_EFFORT
    )

    reference, lower = _estimate_bounds_without_console_noise(request, cache_dir)
    lower_tokens = lower.input_tokens
    upper_tokens = reference.input_tokens
    reference_effort_prefix_tokens = upper_tokens - lower_tokens
    exact_match = lower_tokens == prompt_tokens
    provider_above_lower_reference = prompt_tokens >= lower_tokens
    reference_envelope_non_underestimate = upper_tokens >= prompt_tokens
    effort_prefix_structure_ok = reference_effort_prefix_tokens > 0
    coverage_pass = (
        request_policy_matches
        and provider_above_lower_reference
        and reference_envelope_non_underestimate
        and effort_prefix_structure_ok
    )

    return {
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_COVERAGE",
        "status": "PASS" if coverage_pass else "FAIL",
        "qualification_mode": "CONSERVATIVE_REFERENCE_ENVELOPE_V1",
        "locked_reasoning_effort": LOCKED_REASONING_EFFORT,
        "request_policy_matches": request_policy_matches,
        # Compatibility/audit fields: this is the no-effort-prefix reference,
        # not the production reservation count.
        "estimated_input_tokens": lower_tokens,
        "provider_accounted_input_tokens": lower_tokens,
        "no_effort_prefix_reference_input_tokens": lower_tokens,
        "reference_envelope_input_tokens": upper_tokens,
        "provider_prompt_tokens": prompt_tokens,
        "provider_overhead_vs_lower_reference": prompt_tokens - lower_tokens,
        "reference_effort_prefix_tokens": reference_effort_prefix_tokens,
        "reservation_headroom_tokens": upper_tokens - prompt_tokens,
        "exact_match": exact_match,
        "provider_above_lower_reference": provider_above_lower_reference,
        "reference_envelope_non_underestimate": reference_envelope_non_underestimate,
        "effort_prefix_structure_ok": effort_prefix_structure_ok,
        "coverage_pass": coverage_pass,
        "provider_usage_source_of_truth": True,
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
