from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION = "qualification/PHASE3D_PRODUCT_READINESS_HOST_20260910.json"


def _read(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_paid_ready_locks_are_bound_to_recorded_host_qualification() -> None:
    qualification = _read(QUALIFICATION)
    adcp = _read("ADCP.lock.json")
    estimator = _read("DEEPSEEK_V4_ESTIMATOR.lock.json")
    schedule = _read("PHASE3D_PAIR_SCHEDULE.lock.json")
    plan = _read("PHASE3D_EXPERIMENT_PLAN.json")

    assert qualification["status"] == "PASS"
    assert qualification["qualified_benchmark_commit"] == "7d865382446b2331641b582b8f5b9eaeceaed827"
    assert qualification["raw_report_digest_recorded"] is False

    pins = qualification["pins"]
    assert pins["adcp"] == adcp["commit"] == "e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
    assert qualification["experiment_design"]["schedule_identity"] == schedule["schedule_identity"]
    assert qualification["experiment_design"]["pair_count"] == schedule["pair_count"] == 370
    assert qualification["experiment_design"]["repeat_count_per_task"] == schedule["repeat_count_per_task"] == 37

    assert adcp["host_product_readiness"]["qualification_record"] == QUALIFICATION
    assert adcp["private_pinned_runtime_qualification_status"] == "PASS"
    assert adcp["production_blocker"] is None
    assert adcp["paid_ready"] is True

    coverage = estimator["live_provider_prompt_usage_coverage"]
    assert coverage["qualification_record"] == QUALIFICATION
    assert coverage["status"] == "PASS"
    assert coverage["coverage_pass"] is True
    assert coverage["provider_usage_source_of_truth"] is True
    assert coverage["lower_reference_input_tokens"] <= coverage["provider_prompt_tokens"] <= coverage["reference_envelope_input_tokens"]
    assert estimator["live_provider_prompt_usage_parity"] is True
    assert estimator["production_blocker"] is None
    assert estimator["paid_ready"] is True

    assert qualification["paid_admission"]["paid_ready"] is True
    assert qualification["paid_admission"]["paid_paired_ab_started"] is False
    assert qualification["paid_admission"]["winner"] == "UNKNOWN"
    assert plan["paid_paired_ab"] == "NOT_RUN"
    assert plan["winner"] == "UNKNOWN"
    assert qualification["experiment_design"]["outcome_data_used"] is False
