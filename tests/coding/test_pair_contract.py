"""Pairing/budget regressions. Test boundaries below do not stand in for paid acceptance."""
from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from suites.coding.pair_contract import freeze_pair_contract, assert_episode_binding, validate_pair_rows
from suites.coding.provider.ledger import Ledger
from suites.coding.settings import Settings
from suites.coding.native import NativeDriver


def prepared():
    return [(SimpleNamespace(task_id="issue-test", project_id="owner/repo", description="Fix the issue"),
        {"files": {"package/core.py": "value = 1\n"}, "image": "native:fixed",
         "captured": {"base_source_digest": "sha256:" + "1" * 64}})]


def test_pair_contract_is_explicit_and_never_claims_a_dollar_or_input_token_cap():
    settings = Settings()
    contract = freeze_pair_contract(prepared(), settings)
    assert contract["enrolled_episodes"] == 2
    assert contract["requests_per_arm"] == 16
    assert contract["maximum_requested_output_tokens_per_arm"] == 65536
    assert contract["hard_dollar_cap"] is None
    assert contract["hard_input_token_cap"] is None


def test_mutated_source_environment_or_budget_cannot_enter_the_second_arm():
    settings = Settings()
    data = prepared()
    contract = freeze_pair_contract(data, settings)
    task, payload = data[0]
    assert_episode_binding(contract, task, payload, settings)
    with pytest.raises(ValueError, match="BUDGET"):
        assert_episode_binding(contract, task, payload, replace(settings, requests_per_arm=32))
    payload["image"] = "native:changed"
    with pytest.raises(ValueError, match="INPUT"):
        assert_episode_binding(contract, task, payload, settings)
    payload["image"] = "native:fixed"
    payload["files"]["package/core.py"] = "value = 2\n"
    with pytest.raises(ValueError, match="INPUT"):
        assert_episode_binding(contract, task, payload, settings)


def test_missing_duplicate_or_mismatched_rows_are_not_a_valid_pair():
    contract = freeze_pair_contract(prepared(), Settings())
    before = contract["tasks"][0]["input_digest"]
    rows = [{"task": "issue-test", "project": "owner/repo", "repetition": 0, "arm": arm,
             "input_digest": before, "usage": {"model_requests": 1, "output_tokens": 20, "usage_complete": True}}
            for arm in ("stock", "cycle")]
    assert validate_pair_rows(contract, rows)["same_input_confirmed"]
    for invalid in (rows[:1], [rows[0], rows[0]], [rows[0], {**rows[1], "input_digest": "different"}]):
        with pytest.raises(ValueError):
            validate_pair_rows(contract, invalid)


def test_all_semantic_roles_consume_the_same_arm_quota(tmp_path):
    ledger = Ledger({"tokens": {"a": "stock", "b": "cycle"}, "model": "deepseek-v4-flash",
                     "requests_per_arm": 3, "output_tokens_per_request": 1000}, tmp_path / "usage.json")
    for role in ("architect", "coder", "reviewer"):
        assert ledger.admit("b", {"model": "deepseek-v4-flash"}) >= 1
    with pytest.raises(ValueError, match="BUDGET"):
        ledger.admit("b", {"model": "deepseek-v4-flash"})
    assert ledger.admit("a", {"model": "deepseek-v4-flash"}) == 1
    assert ledger.arms["b"]["admitted"] == 3


def test_materialization_cannot_extend_the_whole_arm_deadline(tmp_path, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("suites.coding.native.time.monotonic", lambda: clock[0])
    class Workspace:
        def materialize(self, files, destination):
            destination.mkdir(parents=True)
            clock[0] += 30
    backend = SimpleNamespace(network="unused", run=lambda *args, **kwargs: pytest.fail("deadline already exhausted"))
    driver = NativeDriver(backend, tmp_path, Settings(), "shared-token", deadline=20, workspace_adapter=Workspace())
    with pytest.raises(TimeoutError, match="ARM_TIME"):
        driver.invoke({"source.py": ""}, "Task")
    assert not driver.invocations


def test_multiple_native_role_requests_keep_one_token_and_decreasing_deadline(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("suites.coding.native.time.monotonic", lambda: clock[0])
    seen = []
    class Backend:
        network = "local-test-only"
        def endpoint(self, token):
            return "http://127.0.0.1/" + token
        def run(self, directory, **options):
            request = json.loads((options["input_path"] / "request.json").read_text())
            seen.append((request, options["timeout"]))
            clock[0] += 10
            results = directory / "results"
            results.mkdir()
            (results / "native.json").write_text(json.dumps({"status": "RETURNED", "text": "test", "finish_reason": "completed"}))
            return SimpleNamespace(succeeded=True, returncode=0, timed_out=False, wall_time_seconds=10)
    driver = NativeDriver(Backend(), tmp_path, Settings(), "same-arm", deadline=160)
    files = {"source.py": "x=1\n"}
    driver.invoke(files, "architect")
    driver.invoke(files, "coder")
    assert [request["endpoint"] for request, _ in seen] == ["http://127.0.0.1/same-arm"] * 2
    assert [timeout for _, timeout in seen] == [60, 50]
    assert len(driver.invocations) == 2
