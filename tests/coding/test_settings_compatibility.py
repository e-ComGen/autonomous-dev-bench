"""Real settings parsing and service admission; no private runtime or model is simulated as PASS."""
from dataclasses import asdict
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from suites.coding.settings import Settings, load_campaign

BUDGETS = '''model = "deepseek-v4-flash"
tasks = 3
repeats = 2
arm_seconds = 321
check_seconds = 45
requests_per_arm = 7
output_tokens_per_request = 2048
request_bytes = 8192
memory_mb = 1024
cpus = 1
max_patch_bytes = 32768
[github]
max_candidates = 9
max_api_requests = 31
prepare_seconds = 120
fetch_seconds = 30
build_seconds = 90
small_projects = 1
medium_projects = 1
large_projects = 1
'''


@pytest.mark.parametrize('backend', ['auto', 'native', 'docker'])
def test_legacy_backend_matches_canonical_without_changing_budgets(tmp_path, backend):
    legacy, canonical = tmp_path / 'legacy.toml', tmp_path / 'canonical.toml'
    legacy.write_text('backend = ' + json.dumps(backend) + '\n' + BUDGETS, encoding='utf-8')
    canonical.write_text('execution_backend = ' + json.dumps(backend) + '\n' + BUDGETS, encoding='utf-8')
    before = legacy.read_bytes()
    settings, policy = load_campaign(legacy)
    assert (settings, policy) == load_campaign(canonical)
    assert settings.execution_backend == backend
    assert settings.requests_per_arm == 7 and settings.arm_seconds == 321
    assert policy.max_candidates == 9 and policy.prepare_seconds == 120
    assert 'backend' not in asdict(settings)
    assert legacy.read_bytes() == before


@pytest.mark.parametrize('backend', ['auto', 'native', 'docker'])
def test_matching_aliases_are_unambiguous(tmp_path, backend):
    path = tmp_path / 'AB.toml'
    path.write_text(f'backend = "{backend}"\nexecution_backend = "{backend}"\n')
    assert load_campaign(path)[0].execution_backend == backend


def test_conflicting_aliases_cannot_be_hidden_by_cli_override(tmp_path):
    from suites.coding.settings import load_launch_settings
    path = tmp_path / 'AB.toml'
    path.write_text('backend = "docker"\nexecution_backend = "native"\n')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Conflicting A/B settings'):
        load_launch_settings(tmp_path, ['ab', '--backend', 'native'])
    assert path.read_bytes() == before


@pytest.mark.parametrize('key', ['backend', 'execution_backend'])
@pytest.mark.parametrize('value', ['true', '1', '[]', '{}', '""', '"unknown"'])
def test_backend_types_and_values_remain_strict(tmp_path, key, value):
    path = tmp_path / 'AB.toml'
    path.write_text(key + ' = ' + value + '\n')
    with pytest.raises(ValueError, match='backend'):
        load_campaign(path)


@pytest.mark.parametrize('extra', [
    'invented_budget = 1\n',
    'requests_per_arm = 0\n',
    '[github]\nimaginary = 2\n',
    '[github]\nsmall_projects = 2\n',
])
def test_alias_does_not_hide_other_configuration_errors(tmp_path, extra):
    path = tmp_path / 'AB.toml'
    path.write_text('backend = "native"\n' + extra)
    with pytest.raises(ValueError):
        load_campaign(path)


@pytest.mark.parametrize('style', ['separate', 'equals', 'absolute'])
def test_early_preflight_uses_root_relative_config_and_cli_precedence(tmp_path, monkeypatch, style):
    from suites.coding.settings import load_launch_settings
    root = tmp_path / 'release with spaces'
    config = root / 'config files' / 'chosen.toml'
    config.parent.mkdir(parents=True)
    config.write_text('backend = "docker"\n' + BUDGETS)
    wrong = tmp_path / 'foreign cwd'
    wrong.mkdir()
    (wrong / 'AB.toml').write_text('invalid = 1\n')
    monkeypatch.chdir(wrong)
    relative = config.relative_to(root).as_posix()
    arguments = (['--ab-config=' + relative, '--backend=native'] if style == 'equals' else
                 ['--ab-config', str(config) if style == 'absolute' else relative, '--backend', 'native'])
    settings = load_launch_settings(root, ['ab', *arguments])
    assert settings.execution_backend == 'native'
    assert settings.requests_per_arm == 7 and settings.arm_seconds == 321
    assert settings.tasks == 3 and settings.repeats == 2


@pytest.mark.parametrize('option', [['--backend', 'invalid'], ['--backend'], ['--ab-config']])
def test_invalid_cli_settings_are_value_errors_before_acquisition(tmp_path, option):
    from suites.coding.settings import load_launch_settings
    (tmp_path / 'AB.toml').write_text('backend = "native"\n')
    with pytest.raises(ValueError, match='Invalid A/B arguments'):
        load_launch_settings(tmp_path, ['ab', *option])


def test_legacy_config_reaches_existing_service_runtime_boundary(tmp_path, monkeypatch):
    from suites.coding import service
    monkeypatch.setattr(service.sys, 'version_info', (3, 12))
    config = tmp_path / 'AB.toml'
    config.write_text('backend = "native"\n' + BUDGETS)
    settings, _ = load_campaign(config)
    seen = []
    def stop_at_runtime(root, scratch, received, **kwargs):
        seen.append(received)
        raise RuntimeError('TEST_STOP_BEFORE_RUNTIME_AND_NETWORK')
    monkeypatch.setattr(service, 'create_runtime', stop_at_runtime)
    arguments = SimpleNamespace(offline=False, ab_config=str(config), backend=None,
        seed=7, command='qualify', allow_local_execution=True)
    with pytest.raises(RuntimeError, match='TEST_STOP_BEFORE_RUNTIME_AND_NETWORK'):
        service.run_ab(tmp_path, arguments, None)
    assert seen == [settings]


def test_no_backend_field_preserves_existing_defaults(tmp_path):
    path = tmp_path / 'AB.toml'
    path.write_text('')
    assert load_campaign(path)[0] == Settings()
