from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from benchmark_core.design_calibration import CalibrationAssumptions, ResourceCaps
from benchmark_core.design_decision import (
    DECISION_SCOPE,
    DesignSelection,
    bind_decision_to_schedule,
    prepare_design_decision,
)
from benchmark_core.design_sensitivity import SensitivityScenario
from benchmark_core.experiment_preregistration import ExperimentDesignSnapshot
from benchmark_core.paired_analysis import PairedExperimentSchedule


REQUIRED_DESIGN_SOURCES = (
    "DEEPSEEK_HARNESS.lock.json",
    "ADCP.lock.json",
    "HARBOR.lock.json",
    "migration/swebench_v5_verified_parity.json",
)


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def _parse_scenarios(raw: dict[str, object]) -> tuple[SensitivityScenario, ...]:
    if raw.get("schema_version") != 1:
        raise SystemExit("sensitivity scenarios must use schema_version 1")
    values = raw.get("scenarios")
    if not isinstance(values, list) or not values:
        raise SystemExit("sensitivity scenarios require a non-empty scenarios list")
    scenarios: list[SensitivityScenario] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise SystemExit(f"scenario {index} must be an object")
        scenario_id = item.get("scenario_id")
        assumptions = item.get("assumptions")
        if not isinstance(scenario_id, str) or not isinstance(assumptions, dict):
            raise SystemExit(f"scenario {index} requires scenario_id and assumptions")
        scenarios.append(
            SensitivityScenario(
                scenario_id=scenario_id,
                assumptions=CalibrationAssumptions(**assumptions),
            )
        )
    return tuple(scenarios)


def _parse_selection(raw: dict[str, object]) -> DesignSelection:
    if raw.get("schema_version") != 1 or raw.get("scope") != DECISION_SCOPE:
        raise SystemExit(f"decision input must be schema_version 1 with scope {DECISION_SCOPE}")
    scenario_id = raw.get("selected_scenario_id")
    decision_reference = raw.get("decision_reference")
    caps = raw.get("resource_caps")
    if not isinstance(scenario_id, str) or not isinstance(decision_reference, str):
        raise SystemExit("decision input requires selected_scenario_id and decision_reference")
    if not isinstance(caps, dict):
        raise SystemExit("decision input requires resource_caps object")
    return DesignSelection(
        scenario_id=scenario_id,
        decision_reference=decision_reference,
        resource_caps=ResourceCaps(**caps),
    )


def _validated_schedule(
    root: Path,
    candidate_plan: dict[str, object],
) -> PairedExperimentSchedule:
    with TemporaryDirectory(prefix="phase3d6-design-") as temp_name:
        temp_root = Path(temp_name)
        for relative in REQUIRED_DESIGN_SOURCES:
            source = root / relative
            target = temp_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        (temp_root / "PHASE3D_EXPERIMENT_PLAN.json").write_text(
            json.dumps(candidate_plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        design = ExperimentDesignSnapshot.from_repository(temp_root)
        schedule = PairedExperimentSchedule.from_design(design)
    return schedule


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind one explicitly selected pre-experiment sensitivity scenario and "
            "explicit resource caps into a reviewed Phase 3D LOCKED-plan candidate."
        )
    )
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("decision", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--plan",
        type=Path,
        help=(
            "explicit DRAFT_BLOCKED plan input; defaults to PHASE3D_EXPERIMENT_PLAN.json "
            "under --root"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = args.output_dir.resolve()
    plan_path = args.plan.resolve() if args.plan is not None else root / "PHASE3D_EXPERIMENT_PLAN.json"
    plan = _read_object(plan_path, "experiment plan")
    scenarios_raw = _read_object(args.scenarios.resolve(), "sensitivity scenarios")
    decision_raw = _read_object(args.decision.resolve(), "design decision")

    scenarios = _parse_scenarios(scenarios_raw)
    selection = _parse_selection(decision_raw)
    candidate_plan, sensitivity_report, decision = prepare_design_decision(
        plan,
        scenarios=scenarios,
        selection=selection,
    )
    schedule = _validated_schedule(root, candidate_plan)
    evidence = bind_decision_to_schedule(decision, schedule)

    _write_json(
        output_dir / "PHASE3D_EXPERIMENT_PLAN.locked.candidate.json",
        candidate_plan,
    )
    _write_json(
        output_dir / "PHASE3D_SENSITIVITY_REPORT.json",
        json.loads(sensitivity_report.to_canonical_json()),
    )
    _write_json(
        output_dir / "PHASE3D_PAIR_SCHEDULE.candidate.json",
        json.loads(schedule.to_canonical_json()),
    )
    _write_json(
        output_dir / "PHASE3D6_DESIGN_DECISION_EVIDENCE.json",
        json.loads(evidence.to_canonical_json()),
    )

    summary = {
        "scope": DECISION_SCOPE,
        "status": "PASS",
        "selected_scenario_id": decision.selected_scenario_id,
        "repeat_count_per_task": decision.repeat_count_per_task,
        "total_pair_count": decision.total_pair_count,
        "total_arm_runs": decision.total_arm_runs,
        "candidate_plan_digest": str(decision.candidate_plan_digest),
        "schedule_identity": str(evidence.schedule_identity),
        "outcome_data_used": False,
        "paid_model_called": False,
        "automatic_scenario_selection": False,
        "plan_committed": False,
        "output_dir": str(output_dir),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
