from pathlib import Path

import pytest

from benchmark_core.swebench_v5 import OfficialSwebenchV5, SwebenchPrediction, require_v5, write_predictions


def test_requires_current_v5_pin():
    assert require_v5("swebench 5.0.2") == (5, 0, 2)
    with pytest.raises(ValueError):
        require_v5("swebench 4.0.3")


def test_official_gold_command_uses_v5_cli_and_task_repo():
    evaluator = OfficialSwebenchV5(task_repo=Path("/tasks"), workers=3, timeout_seconds=900)
    command = evaluator.gold_command("parity-gold", ["sympy__sympy-20590", "psf__requests-2931"])

    assert command[:3] == ("swebench", "eval", "verified")
    assert "--gold" in command
    assert command.count("-i") == 2
    assert Path(command[command.index("--task-repo") + 1]) == Path("/tasks")


def test_prediction_command_and_jsonl_are_canonical(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    write_predictions(
        predictions,
        [SwebenchPrediction("sympy__sympy-20590", "diff --git a/a b/a\n", "stock-deepseek")],
    )
    line = predictions.read_text(encoding="utf-8")
    assert line == (
        '{"instance_id":"sympy__sympy-20590","model_name_or_path":"stock-deepseek",'
        '"model_patch":"diff --git a/a b/a\\n"}\n'
    )

    evaluator = OfficialSwebenchV5()
    command = evaluator.prediction_command("parity-empty", ["sympy__sympy-20590"], predictions)
    assert "--gold" not in command
    assert command[command.index("-p") + 1] == str(predictions)


def test_results_path_matches_official_v5_layout(tmp_path):
    evaluator = OfficialSwebenchV5()
    expected = tmp_path / "logs" / "evaluation" / "parity" / "results.json"
    assert evaluator.results_path(tmp_path, "parity") == expected
