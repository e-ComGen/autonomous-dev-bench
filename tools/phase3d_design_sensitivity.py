from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_core.design_calibration import CalibrationAssumptions
from benchmark_core.design_sensitivity import SensitivityScenario, build_sensitivity_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate explicit pre-experiment Phase 3D power scenarios without "
            "choosing a scenario or reading experiment outcomes."
        )
    )
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("--plan", type=Path, default=Path("PHASE3D_EXPERIMENT_PLAN.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SystemExit("experiment plan must be a JSON object")
    corpus = plan.get("corpus")
    tasks = corpus.get("tasks") if isinstance(corpus, dict) else None
    if not isinstance(tasks, list) or not tasks or any(not isinstance(item, str) for item in tasks):
        raise SystemExit("experiment plan has no valid task list")
    if plan.get("paid_paired_ab") != "NOT_RUN" or plan.get("winner") != "UNKNOWN":
        raise SystemExit("sensitivity analysis is forbidden after paid experiment outcomes exist")

    raw = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SystemExit("sensitivity input must be schema_version 1 object")
    values = raw.get("scenarios")
    if not isinstance(values, list) or not values:
        raise SystemExit("sensitivity input requires a non-empty scenarios list")

    scenarios: list[SensitivityScenario] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise SystemExit(f"scenario {index} must be an object")
        scenario_id = item.get("scenario_id")
        assumptions_raw = item.get("assumptions")
        if not isinstance(scenario_id, str) or not isinstance(assumptions_raw, dict):
            raise SystemExit(f"scenario {index} requires scenario_id and assumptions")
        scenarios.append(
            SensitivityScenario(
                scenario_id=scenario_id,
                assumptions=CalibrationAssumptions(**assumptions_raw),
            )
        )

    report = build_sensitivity_report(task_count=len(tasks), scenarios=scenarios)
    payload = json.loads(report.to_canonical_json())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
