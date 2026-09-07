from dataclasses import replace
from pathlib import Path
import pytest

from cli.oneclick.catalog import read_catalog
from cli.oneclick.config import load_config
from cli.oneclick.plan import make_plan

ROOT = Path(__file__).resolve().parents[2]


def test_current_catalog_and_plan_are_deterministic():
    config = load_config(ROOT / "BENCHMARK.toml")
    catalog = read_catalog(ROOT)
    assert len(catalog) == 3
    first = make_plan(config, catalog)
    assert first == make_plan(config, tuple(reversed(catalog)))
    assert first["requested_episode_slots"] == 60
    assert first["quota_satisfied"]
    assert first["qualified_coding_tasks"] == 0
    assert first["execution_ready"] is False
    assert first["actual_api_usd"] is None


def test_large_quota_cannot_be_filled_by_small_projects():
    config = replace(load_config(ROOT / "BENCHMARK.toml"), quotas=(("large", 2),))
    plan = make_plan(config, read_catalog(ROOT))
    assert plan["projects"] == []
    assert plan["quota_deficits"] == {"large": 2}


@pytest.mark.parametrize("old,new", [
    ('repetitions = 2', 'repetitions = true'),
    ('tasks_per_project = 5', 'tasks_per_project = -1'),
    ('seed = 41', 'seed = -1'),
    ('large = 0', 'large = -1'),
    ('planned_usd_per_episode = 1.0', 'planned_usd_per_episode = nan'),
    ('test_seconds = 900', 'test_seconds = 0'),
    ('max_response_bytes = 2097152', 'max_response_bytes = 0'),
    ('"pluggy.pinned_001"', '"../../bad"'),
    ('"development_cycle"', '"default_dsh"'),
    ('"autobench.campaign/v1"', '"unknown"'),
])
def test_invalid_configuration_is_rejected(tmp_path, old, new):
    text = (ROOT / "BENCHMARK.toml").read_text()
    path = tmp_path / "bad.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_unknown_config_field_is_not_ignored(tmp_path):
    path = tmp_path / "extra.toml"
    path.write_text('invented = 1\n' + (ROOT / "BENCHMARK.toml").read_text())
    with pytest.raises(ValueError):
        load_config(path)


def test_unknown_project_fails_before_work():
    config = replace(load_config(ROOT / "BENCHMARK.toml"), projects=("invented",))
    with pytest.raises(ValueError):
        make_plan(config, read_catalog(ROOT))
