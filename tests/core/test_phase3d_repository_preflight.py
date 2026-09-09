from pathlib import Path

from benchmark_core.paired_experiment import PaidAdmissionSnapshot


ROOT = Path(__file__).resolve().parents[2]


def test_current_repository_paid_preflight_is_fail_closed_on_known_external_gates() -> None:
    admission = PaidAdmissionSnapshot.from_repository(ROOT)

    assert admission.paid_ready is False
    assert admission.expected_model == "deepseek-v4-flash"
    assert admission.expected_provider == "deepseek-official"
    assert admission.stock_model_matches is True
    assert admission.adcp_model_matches is True
    assert admission.estimator_model_matches is True
    assert admission.provider_routes_match is True
    assert admission.adcp_fake_process_boundary_pass is True
    assert admission.blockers == (
        "DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS",
        "DEEPSEEK_ESTIMATOR_NOT_PAID_READY",
        "ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS",
        "ADCP_NOT_PAID_READY",
    )
