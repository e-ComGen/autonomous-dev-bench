import json
from pathlib import Path

from cli.main import main
from benchmark_core.result import HardGate


def test_scenario_validator_rejects_answers(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({"scenario_id": "x", "expected_answer": "leak"}), encoding="utf-8")
    assert main(["validate-scenario", str(path)]) == 2


def test_hard_gate_counter_is_noncompensable(tmp_path: Path) -> None:
    path = tmp_path / "gates.json"
    counters = {gate.value: 0 for gate in HardGate}
    counters["false_safe_certificate"] = 1
    path.write_text(json.dumps(counters), encoding="utf-8")
    assert main(["check-hard-gates", str(path)]) == 1


def test_zero_known_hard_gates_pass(tmp_path: Path) -> None:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps({gate.value: 0 for gate in HardGate}), encoding="utf-8")
    assert main(["check-hard-gates", str(path)]) == 0
