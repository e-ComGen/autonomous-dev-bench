import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from suites.coding.provider.ledger import Ledger, AdmissionDenied, totals
from cli.oneclick.report import Report


def ledger(tmp_path, requests=2):
    return Ledger({"tokens": {"secret-arm-token": "stock"}, "model": "deepseek-v4-flash",
                   "requests_per_arm": requests, "output_tokens_per_request": 1000}, tmp_path / "usage.json")


def test_admission_clamps_all_native_requests_and_hides_tokens(tmp_path):
    value = ledger(tmp_path)
    request = {"model": "deepseek-v4-flash", "max_tokens": 2000, "stream": True}
    assert value.admit("secret-arm-token", request) == 1
    assert request["max_tokens"] == 1000
    assert request["stream_options"] == {"include_usage": True}
    assert "secret-arm-token" not in (tmp_path / "usage.json").read_text()
    state = json.loads((tmp_path / "usage.json").read_text())["stock"]
    assert totals(state)["input_tokens"] is None
    assert totals(state)["cost_usd"] is None


def test_concurrent_budget_cannot_over_admit(tmp_path):
    value = ledger(tmp_path, 3)
    def invoke(_):
        try:
            return value.admit("secret-arm-token", {"model": "deepseek-v4-flash"})
        except AdmissionDenied:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        admitted = list(executor.map(invoke, range(30)))
    assert len([item for item in admitted if item is not None]) == 3


def test_provider_usage_has_no_invented_zero_or_duplicate_completion(tmp_path):
    value = ledger(tmp_path)
    sequence = value.admit("secret-arm-token", {"model": "deepseek-v4-flash"})
    value.complete("secret-arm-token", sequence, {"prompt_tokens": 55, "completion_tokens": 12}, "RETURNED")
    state = json.loads((tmp_path / "usage.json").read_text())["stock"]
    assert totals(state)["input_tokens"] == 55
    assert totals(state)["output_tokens"] == 12
    with pytest.raises(ValueError):
        value.complete("secret-arm-token", sequence, None, "RETURNED")
    value.admit("secret-arm-token", {"model": "deepseek-v4-flash"})
    state = json.loads((tmp_path / "usage.json").read_text())["stock"]
    assert totals(state)["input_tokens"] is None


def test_model_swap_and_unknown_arm_are_rejected_before_admission(tmp_path):
    value = ledger(tmp_path)
    for token, model in [("wrong", "deepseek-v4-flash"), ("secret-arm-token", "other")]:
        with pytest.raises(AdmissionDenied):
            value.admit(token, {"model": model})
    assert value.arms["secret-arm-token"]["admitted"] == 0


def test_reports_do_not_overwrite_real_model_execution_with_false(tmp_path):
    report = Report(tmp_path, "ab")
    path = report.save({"status": "AB_COMPLETE", "live_model_called": True, "rows": [{"arm": "stock"}]})
    assert json.loads(path.read_text())["live_model_called"] is True
