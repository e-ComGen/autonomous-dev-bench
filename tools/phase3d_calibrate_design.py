from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.design_calibration import (
    CalibrationAssumptions,
    ResourceCaps,
    calibrate_repeat_count,
    canonical_json_sha256,
    compile_locked_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile an outcome-blind Phase 3D LOCKED experiment-plan candidate "
            "from explicit power assumptions and explicit resource caps."
        )
    )
    parser.add_argument("--plan", type=Path, default=Path("PHASE3D_EXPERIMENT_PLAN.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-discordant-rate", type=float, required=True)
    parser.add_argument("--adcp-win-probability-given-discordance", type=float, required=True)
    parser.add_argument("--target-power", type=float, required=True)
    parser.add_argument("--max-repeat-count", type=int, required=True)
    parser.add_argument(
        "--assumption-source",
        choices=("external_prior", "preexperiment_pilot", "budget_sensitivity_scenario"),
        required=True,
    )
    parser.add_argument("--assumption-reference", required=True)
    parser.add_argument("--total-model-token-cap-per-arm", type=int, required=True)
    parser.add_argument("--input-token-cap-per-arm", type=int, required=True)
    parser.add_argument("--output-token-cap-per-arm", type=int, required=True)
    parser.add_argument("--max-requests-per-arm", type=int, required=True)
    parser.add_argument("--wall-time-seconds-per-arm", type=int, required=True)
    parser.add_argument("--patch-byte-cap-per-arm", type=int, required=True)
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    output_path = args.output.resolve()
    if plan_path == output_path:
        raise SystemExit(
            "refusing in-place preregistration mutation; write a candidate to a distinct path, review it, then commit it explicitly"
        )

    raw = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("experiment plan must be a JSON object")

    assumptions = CalibrationAssumptions(
        expected_discordant_rate=args.expected_discordant_rate,
        adcp_win_probability_given_discordance=args.adcp_win_probability_given_discordance,
        target_power=args.target_power,
        max_repeat_count=args.max_repeat_count,
        assumption_source=args.assumption_source,
        assumption_reference=args.assumption_reference,
    )
    caps = ResourceCaps(
        total_model_token_cap_per_arm=args.total_model_token_cap_per_arm,
        input_token_cap_per_arm=args.input_token_cap_per_arm,
        output_token_cap_per_arm=args.output_token_cap_per_arm,
        max_requests_per_arm=args.max_requests_per_arm,
        wall_time_seconds_per_arm=args.wall_time_seconds_per_arm,
        patch_byte_cap_per_arm=args.patch_byte_cap_per_arm,
    )

    tasks = raw.get("corpus", {}).get("tasks") if isinstance(raw.get("corpus"), dict) else None
    if not isinstance(tasks, list):
        raise SystemExit("experiment plan has no valid corpus task list")
    calibration = calibrate_repeat_count(task_count=len(tasks), assumptions=assumptions)
    locked = compile_locked_plan(raw, assumptions=assumptions, caps=caps)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(locked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "scope": "PHASE3D4_OUTCOME_BLIND_DESIGN_CALIBRATION",
        "status": "PASS",
        "input_plan_sha256": canonical_json_sha256(raw),
        "candidate_plan_sha256": canonical_json_sha256(locked),
        "method": calibration.method,
        "task_count": calibration.task_count,
        "repeat_count_per_task": calibration.repeat_count_per_task,
        "total_pair_count": calibration.total_pair_count,
        "target_power": calibration.target_power,
        "achieved_power": calibration.achieved_power,
        "expected_discordant_pairs": calibration.expected_discordant_pairs,
        "implied_resolution_rate_difference": calibration.implied_resolution_rate_difference,
        "outcome_data_used": False,
        "paid_model_called": False,
        "output": str(output_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
