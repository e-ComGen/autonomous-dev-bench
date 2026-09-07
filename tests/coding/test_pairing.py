from types import SimpleNamespace
import sys
from suites.coding.experiment import schedule, run_episode
from suites.coding.recipes import RECIPES
from suites.coding.settings import Settings
from cli.oneclick.report import Report


def test_pair_schedule_has_exactly_one_of_each_arm_on_same_input():
    task = RECIPES[0]
    data = {"files": {"example.py": "x=1\n"}}
    planned = schedule([(task, data)], 3, 21)
    assert len(planned) == 6
    for repetition in range(3):
        pair = [item for item in planned if item[2] == repetition]
        assert {item[3] for item in pair} == {"stock", "cycle"}
        assert all(item[1] is data for item in pair)
    assert planned == schedule([(task, data)], 3, 21)


def test_model_failure_remains_an_enrolled_external_failure(tmp_path, monkeypatch):
    # This substitutes a transport boundary in a host unit test, never production.
    monkeypatch.setitem(sys.modules, "suites.coding.cycle", SimpleNamespace(cycle_arm=None))
    def failed(*args):
        raise RuntimeError("model connection lost")
    monkeypatch.setattr("suites.coding.experiment.stock_arm", failed)
    evaluator = SimpleNamespace(score=lambda *args: {"status": "FAIL"})
    data = {"files": {"package/core.py": "raise NotImplementedError()\n"}, "checks": [], "expected": []}
    result = run_episode(tmp_path, RECIPES[0], data, 0, "stock", None, evaluator,
                         "token", Settings(), Report(tmp_path, "ab"), tmp_path)
    assert result["execution"] == "EXECUTION_ERROR"
    assert result["solved"] is False
    assert result["input_digest"] == result["candidate_digest"]
    assert result["patch_ref"].startswith("cas:")
