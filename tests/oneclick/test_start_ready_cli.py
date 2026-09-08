"""Actual launchers on supported interpreters and fail-closed behavior on older Python."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]


def copy_entrypoint(tmp_path):
    root = tmp_path / 'folder with spaces'
    tools = root / 'tools'
    tools.mkdir(parents=True)
    for name in ('start_ready.py', 'launcher_credentials.py'):
        shutil.copyfile(ROOT / 'tools' / name, tools / name)
    # Use the real configuration reader, not a test-only compatibility shim.
    for package in ('suites', 'suites/coding', 'corpus', 'corpus/qualification'):
        directory = root / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / '__init__.py').write_text('')
    for relative in ('suites/coding/settings.py', 'corpus/qualification/policy.py'):
        shutil.copyfile(ROOT / relative, root / relative)
    (root / 'AB.toml').write_text('backend = "native"\n')
    shutil.copyfile(ROOT / 'START.cmd', root / 'START.cmd')
    (tools / 'prepare_ab.py').write_text(
        'from pathlib import Path\ndef prepare_runtime():\n'
        '    Path("runtime-called.txt").write_text("TEST BOUNDARY: no private acquisition")\n')
    (tools / 'launch.py').write_text(
        'import json,os,sys\nfrom pathlib import Path\n'
        'value={"argv":sys.argv[1:],"python":list(sys.version_info[:3]),'
        '"github":bool(os.environ.get("GITHUB_TOKEN")),"model":bool(os.environ.get("DEEPSEEK_API_KEY"))}\n'
        'sys.path.insert(0,str(Path.cwd()))\n'
        'if not any(item in sys.argv for item in ("--help","-h")):\n'
        '    from suites.coding.settings import load_launch_settings\n'
        '    settings=load_launch_settings(Path.cwd(),sys.argv[1:])\n'
        '    value.update(backend=settings.execution_backend,requests=settings.requests_per_arm)\n'
        'Path("observed.json").write_text(json.dumps(value))\n'
        'raise SystemExit(7)\n')
    return root


def invoke(root, env, *args):
    if os.name == 'nt':
        command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'START.cmd', *args]
    else:
        command = [sys.executable, '-I', 'tools/start_ready.py', *args]
    return subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=15, shell=False)


def selected_interpreter(root, environment):
    # The Windows launcher may select Python 3.12 even when pytest runs on 3.11.
    # Probe its real selection through the existing non-billable help dispatch.
    probe = invoke(root, environment, '--help')
    assert probe.returncode == 7, probe.stdout + probe.stderr
    path = root / 'observed.json'
    version = tuple(json.loads(path.read_text())['python'])
    path.unlink()
    return version


def no_real_keys():
    return {key: value for key, value in os.environ.items()
            if key not in {'GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'AUTOBENCH_ALLOW_PAID'}}


@pytest.mark.parametrize('file_switch', [None, 'NO', 'YES', 'false'])
@pytest.mark.parametrize('environment_switch', [None, 'NO', 'false', '0'])
def test_real_batch_always_dispatches_paid_ab_regardless_of_legacy_switch(tmp_path, file_switch, environment_switch):
    root = copy_entrypoint(tmp_path)
    content = 'GITHUB_TOKEN=not-a-real-github-token\nDEEPSEEK_API_KEY=not-a-real-model-key\n'
    if file_switch is not None:
        content += 'AUTOBENCH_ALLOW_PAID=' + file_switch + '\n'
    (root / '.env').write_text(content)
    original = (root / '.env').read_bytes()
    environment = no_real_keys()
    if environment_switch is not None:
        environment['AUTOBENCH_ALLOW_PAID'] = environment_switch
    version = selected_interpreter(root, environment)
    result = invoke(root, environment)
    if version < (3, 12):
        assert result.returncode == 2 and 'Python 3.12 or newer' in result.stderr
        assert not (root / 'observed.json').exists()
        assert json.loads((root / '.bench/startup.json').read_text())['status'] == 'BLOCKED'
    else:
        assert result.returncode == 7, result.stdout + result.stderr
        observed = json.loads((root / 'observed.json').read_text())
        assert observed['github'] and observed['model']
        assert observed['argv'] == ['ab', '--allow-live-model', '--allow-local-execution']
        assert observed['backend'] == 'native'
        assert json.loads((root / '.bench/startup.json').read_text())['status'] == 'DISPATCHING'
    assert 'not-a-real-' not in result.stdout + result.stderr
    assert 'Type YES' not in result.stdout and '[Y/N]' not in result.stdout
    assert 'AUTOBENCH_ALLOW_PAID' not in result.stdout + result.stderr
    assert (root / '.env').read_bytes() == original
    assert json.loads((root / '.bench/startup.json').read_text())['launcher'] == 'paid-ab-default-v2'


def test_real_missing_key_path_ends_without_hanging_on_stdin(tmp_path):
    root = copy_entrypoint(tmp_path)
    environment = no_real_keys()
    version = selected_interpreter(root, environment)
    result = invoke(root, environment)
    assert result.returncode == 2, result.stdout + result.stderr
    if version < (3, 12):
        assert 'Python 3.12 or newer' in result.stderr
        assert not (root / '.env').exists()
    else:
        assert 'GITHUB_TOKEN' in result.stderr and '.env' in result.stderr
        assert (root / '.env').is_file()
    assert 'AUTOBENCH_ALLOW_PAID' not in result.stderr
    assert not (root / 'observed.json').exists()


@pytest.mark.parametrize('configuration,reason', [
    ('backend = "native"\ninvented_budget = 1\n', 'Unknown A/B settings'),
    ('backend = "docker"\nexecution_backend = "native"\n', 'Conflicting A/B settings'),
    ('backend = "native"\nrequests_per_arm = 0\n', 'requests_per_arm'),
    ('backend = true\n', 'backend must be'),
    (None, 'missing.toml'),
])
@pytest.mark.parametrize('command', ['ab', 'ab-preflight', 'qualify'])
def test_real_launcher_config_failure_precedes_runtime_and_dispatch(tmp_path, configuration, reason, command):
    root = copy_entrypoint(tmp_path)
    (root / '.env').write_text('GITHUB_TOKEN=test-only-gh\nDEEPSEEK_API_KEY=test-only-model\n')
    environment = no_real_keys()
    version = selected_interpreter(root, environment)
    path = root / 'missing.toml'
    if configuration is not None:
        path.write_text(configuration)
    result = invoke(root, environment, command, '--ab-config', path.name)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (reason if version >= (3, 12) else 'Python 3.12 or newer') in result.stderr
    assert not (root / 'runtime-called.txt').exists()
    assert not (root / 'observed.json').exists()
    assert json.loads((root / '.bench/startup.json').read_text())['status'] == 'BLOCKED'
    assert 'test-only-' not in result.stdout + result.stderr
    if configuration is not None:
        assert path.read_text() == configuration


def test_real_launcher_custom_config_and_cli_override_keep_budget(tmp_path):
    root = copy_entrypoint(tmp_path)
    (root / '.env').write_text('GITHUB_TOKEN=test-only-gh\nDEEPSEEK_API_KEY=test-only-model\n')
    (root / 'AB.toml').write_text('invalid_default = 1\n')
    # The batch already runs inside a path with spaces; custom relative paths
    # are additionally verified by the real settings reader's own tests.
    path = root / 'custom.toml'
    path.write_text('backend = "docker"\nrequests_per_arm = 7\n')
    before = path.read_bytes()
    environment = no_real_keys()
    version = selected_interpreter(root, environment)
    result = invoke(root, environment, 'ab', '--ab-config=custom.toml', '--backend=native')
    if version < (3, 12):
        assert result.returncode == 2 and 'Python 3.12 or newer' in result.stderr
    else:
        assert result.returncode == 7, result.stdout + result.stderr
        observed = json.loads((root / 'observed.json').read_text())
        assert observed['backend'] == 'native' and observed['requests'] == 7
        assert (root / 'runtime-called.txt').is_file()
        assert 'settings-v2' in result.stdout
    assert path.read_bytes() == before
