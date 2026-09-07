from dataclasses import replace
from pathlib import Path
import ast
import pytest

from suites.coding.settings import Settings, load_settings
from suites.coding.selection import candidate_order, selection_digest
from suites.coding.recipes import RECIPES
from suites.coding.source import omit_function, snapshot_files, write_files
from cli.oneclick.main import parser


def test_default_command_is_ab_and_test_remains_explicit():
    assert parser().parse_args([]).command == "ab"
    assert parser().parse_args(["test", "--offline"]).command == "test"


@pytest.mark.parametrize("key", ["tasks", "repeats", "arm_seconds", "requests_per_arm", "memory_mb"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_invalid_budgets_are_rejected(key, value):
    with pytest.raises(ValueError):
        replace(Settings(), **{key: value})


def test_config_rejects_ignored_settings(tmp_path):
    path = tmp_path / "AB.toml"
    path.write_text('imaginary_budget = 10\n')
    with pytest.raises(ValueError, match="Unknown"):
        load_settings(path)


def test_seed_freezes_task_order_without_replacement():
    settings = Settings()
    first = candidate_order(settings.projects, 17)
    assert first == candidate_order(settings.projects, 17)
    assert len(first) == 6 and {item.task_id for item in first} == {item.task_id for item in RECIPES}
    assert selection_digest(first, settings) != selection_digest(first, replace(settings, repeats=2))


def test_multiple_seeds_cover_multiple_real_projects_and_tasks():
    selected = [candidate_order(Settings().projects, seed)[0] for seed in range(100)]
    assert len({item.project_id for item in selected}) == 3
    assert len({item.task_id for item in selected}) == 6


def test_source_mutation_preserves_adjacent_functions_and_docstring():
    source = 'def target(x):\n    """Public contract."""\n    return x + 2\n\ndef neighbor():\n    return 9\n'
    result = omit_function(source, "target")
    ast.parse(result)
    assert '"""Public contract."""' in result
    assert "return x + 2" not in result
    assert "def neighbor():\n    return 9" in result
    with pytest.raises(ValueError):
        omit_function(source, "absent")


def test_source_projection_roundtrip_and_protected_paths(tmp_path):
    files = {"package/core.py": "x = 1\n", "TASK.md": "Objective\n"}
    write_files(tmp_path / "source", files)
    assert snapshot_files(tmp_path / "source") == files
    with pytest.raises(ValueError):
        write_files(tmp_path / "source", {"../escape": "bad"})


def test_new_coding_implementation_modules_remain_bounded():
    root = Path(__file__).resolve().parents[2]
    for path in (root / "suites/coding").rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 220, path
