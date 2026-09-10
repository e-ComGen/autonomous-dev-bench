from pathlib import Path

from benchmark_core.paired_experiment import PaidAdmissionSnapshot


ROOT = Path(__file__).resolve().parents[2]


def test_current_repository_paid_preflight_is_ready_after_recorded_host_qualification() -> None:
    admission = PaidAdmissionSnapshot.from_repository(ROOT)

    assert admission.paid_ready is True
    assert admission.expected_model == "deepseek-v4-flash"
    assert admission.expected_provider == "deepseek-official"
    assert admission.experiment_design.design_paid_ready is True
    assert admission.experiment_design.repeat_count_per_task == 37
    assert admission.experiment_design.required_completed_pairs == 370
    assert len(admission.experiment_design.task_ids) == 10
    assert admission.stock_model_matches is True
    assert admission.adcp_model_matches is True
    assert admission.estimator_model_matches is True
    assert admission.provider_routes_match is True
    assert admission.estimator_live_prompt_parity is True
    assert admission.estimator_paid_ready is True
    assert admission.adcp_fake_process_boundary_pass is True
    assert admission.adcp_private_runtime_status == "PASS"
    assert admission.adcp_paid_ready is True
    assert admission.blockers == ()
