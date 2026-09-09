from __future__ import annotations

import json
from pathlib import Path

from benchmark_core.design_calibration import CalibrationAssumptions, ResourceCaps
from benchmark_core.design_decision import DesignSelection, prepare_design_decision
from benchmark_core.design_sensitivity import SensitivityScenario
from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_experiment import PaidAdmissionSnapshot


ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> dict[str, object]:
    value = json.loads((ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_phase3d7_selected_inputs_reproduce_committed_lock_without_outcomes() -> None:
    prelock = _read("PHASE3D_EXPERIMENT_PLAN.prelock.json")
    locked = _read("PHASE3D_EXPERIMENT_PLAN.json")
    scenarios_raw = _read("PHASE3D_DESIGN_SCENARIOS.json")
    decision_raw = _read("PHASE3D_DESIGN_DECISION.json")
    sensitivity_committed = _read("PHASE3D_SENSITIVITY_REPORT.json")
    evidence_committed = _read("PHASE3D_DESIGN_DECISION_EVIDENCE.json")

    assert prelock["status"] == "DRAFT_BLOCKED"
    assert locked["status"] == "LOCKED"
    assert locked["paid_paired_ab"] == "NOT_RUN"
    assert locked["winner"] == "UNKNOWN"
    assert decision_raw["outcome_data_used"] is False
    assert decision_raw["paid_model_called"] is False
    assert decision_raw["automatic_scenario_selection"] is False

    scenarios = tuple(
        SensitivityScenario(
            scenario_id=item["scenario_id"],
            assumptions=CalibrationAssumptions(**item["assumptions"]),
        )
        for item in scenarios_raw["scenarios"]
    )
    selection = DesignSelection(
        scenario_id=decision_raw["selected_scenario_id"],
        decision_reference=decision_raw["decision_reference"],
        resource_caps=ResourceCaps(**decision_raw["resource_caps"]),
    )

    candidate, sensitivity, decision = prepare_design_decision(
        prelock,
        scenarios=scenarios,
        selection=selection,
    )

    rows = {row.scenario_id: row for row in sensitivity.rows}
    assert rows["mde-10pp-conservative-discordance"].repeat_count_per_task == 81
    assert rows["mde-15pp-conservative-discordance"].repeat_count_per_task == 37
    assert rows["mde-20pp-conservative-discordance"].repeat_count_per_task == 21
    assert decision.selected_scenario_id == "mde-15pp-conservative-discordance"
    assert decision.repeat_count_per_task == 37
    assert decision.total_pair_count == 370
    assert decision.total_arm_runs == 740
    assert decision.aggregate_total_model_token_ceiling == 193986560
    assert decision.aggregate_output_token_ceiling == 48496640
    assert decision.aggregate_request_ceiling == 11840
    assert decision.aggregate_arm_wall_time_budget_seconds == 444000
    assert candidate == locked
    assert json.loads(sensitivity.to_canonical_json()) == sensitivity_committed
    assert str(Sha256Digest.of(candidate)) == evidence_committed["decision"]["candidate_plan_digest"]["value"]
    assert str(sensitivity.content_digest) == evidence_committed["decision"]["sensitivity_report_digest"]["value"]


def test_locked_design_does_not_bypass_external_paid_admission_gates() -> None:
    admission = PaidAdmissionSnapshot.from_repository(ROOT)

    assert admission.experiment_design.design_paid_ready is True
    assert admission.paid_ready is False
    assert "DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS" in admission.blockers
    assert "DEEPSEEK_ESTIMATOR_NOT_PAID_READY" in admission.blockers
    assert "ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS" in admission.blockers
    assert "ADCP_NOT_PAID_READY" in admission.blockers
