"""Real bench.py credential boundary tests; no network/model/runtime qualification claims."""
from pathlib import Path
import importlib.util
import pytest
from tools.launch import command_name, host_environment

_spec = importlib.util.spec_from_file_location('credential_probe_fixture', Path(__file__).with_name('credential_probe_fixture.py'))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
populate, credentials, invoke, clean_parent = _fixture.populate, _fixture.credentials, _fixture.invoke, _fixture.clean_parent


def assert_children_scrubbed(observed):
    assert not observed['host']['OPENAI_API_KEY']
    assert not observed['host']['OTHER_SECRET']
    assert observed['api_requests'] == 0 and not observed['model_called']
    assert set(observed['children']) == {'bootstrap', 'native'}
    assert all(not any(values.values()) for values in observed['children'].values())


@pytest.mark.parametrize('source', ['dotenv', 'dotenv-alias', 'environment', 'environment-alias'])
def test_actual_bench_ab_retains_both_provider_boundaries(tmp_path, source):
    root = populate(tmp_path / 'actual bench with spaces')
    environment = credentials(root, source)
    original = (root / '.env').read_bytes()
    observed = invoke(root, ['ab', '--allow-live-model'], environment)
    assert observed['github_error'] is None, observed
    assert observed['provider_error'] is None, observed
    assert observed['github_matches'] and observed['provider_matches']
    assert observed['host']['GITHUB_TOKEN'] and observed['host']['GH_TOKEN']
    assert observed['host']['DEEPSEEK_API_KEY']
    assert (root / '.env').read_bytes() == original
    assert_children_scrubbed(observed)


@pytest.mark.parametrize('command', ['ab-preflight', 'qualify', 'discover'])
@pytest.mark.parametrize('source', ['dotenv', 'environment-alias'])
def test_nonpaid_acquisition_gets_only_github(tmp_path, command, source):
    root = populate(tmp_path / 'credential policy')
    observed = invoke(root, [command], credentials(root, source))
    assert observed['github_error'] is None and observed['github_matches']
    assert not observed['host']['DEEPSEEK_API_KEY']
    assert_children_scrubbed(observed)


@pytest.mark.parametrize('arguments', [
    ['test'], ['doctor'], ['catalog'], ['plan'], ['projects'], ['_project'],
    ['--help'], ['ab', '--help'], ['qualify', '-h'], ['discover', '--help'],
])
def test_diagnostics_do_not_read_dotenv_or_forward_credentials(tmp_path, arguments):
    root = populate(tmp_path / 'diagnostic boundary')
    environment = credentials(root, 'environment')
    (root / '.env').write_text('GITHUB_TOKEN="unterminated\n', encoding='utf-8')
    observed = invoke(root, arguments, environment)
    assert not any(observed['host'].values())
    assert not observed['docker_config_present']
    assert_children_scrubbed(observed)


def test_missing_host_keys_remain_explicit_missing_not_success(tmp_path):
    root = populate(tmp_path / 'missing credentials')
    observed = invoke(root, ['ab'], clean_parent())
    assert observed['github_error'] == 'GITHUB_TOKEN_MISSING'
    assert observed['provider_error'] == 'DEEPSEEK_API_KEY_MISSING'
    assert_children_scrubbed(observed)


def test_default_bench_command_uses_same_paid_host_policy(tmp_path):
    root = populate(tmp_path / 'default command')
    observed = invoke(root, [], credentials(root))
    assert observed['github_matches'] and observed['provider_matches']
    assert_children_scrubbed(observed)


def test_actual_launch_host_environment_survives_next_scrub(tmp_path, monkeypatch):
    root = populate(tmp_path / 'two actual scrubs')
    values = credentials(root, 'environment-alias')
    for key in ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY'):
        monkeypatch.delenv(key, raising=False)
        if key in values:
            monkeypatch.setenv(key, values[key])
    monkeypatch.setenv('DOCKER_CONFIG', str(root / 'operator docker'))
    environment = host_environment(root, 'ab')
    observed = invoke(root, ['ab'], environment)
    assert observed['github_matches'] and observed['provider_matches']
    assert observed['docker_config_present']
    assert_children_scrubbed(observed)


@pytest.mark.parametrize('arguments', [[], ['ab'], ['--backend', 'native']])
def test_command_policy_defaults_to_ab(arguments):
    assert command_name(arguments) == 'ab'


@pytest.mark.parametrize('arguments', [['--help'], ['ab', '--help'], ['discover', '-h']])
def test_help_policy_is_not_paid_or_network_admission(arguments):
    assert command_name(arguments) == 'help'
