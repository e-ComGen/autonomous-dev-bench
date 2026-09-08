"""Host transaction tests. External Git/qualification boundaries are replaced only here."""
from pathlib import Path
import hashlib
import json
import pytest
import tools.runtime_install as installer
from suites.coding.adcp_loading import ADCP_COMMIT, verify_distribution


def distribution(path, commit=ADCP_COMMIT):
    path.mkdir(parents=True)
    files = {name: '# unit-test source bytes\n' for name in
             ('packages/zone_development/contracts.py', 'packages/zone_development/workspace.py',
              'packages/zone_development/snapshot_reader.py')}
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode('utf-8'))
    manifest = {'commit': commit, 'files': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in files.items()}}
    (path / 'SOURCE.json').write_text(json.dumps(manifest), encoding='utf-8')


def test_failed_gate_keeps_existing_runtime_and_cleans_pending_stage(tmp_path, monkeypatch):
    target = tmp_path / '.bench/adcp'
    distribution(target, 'old-pin')
    original = (target / 'SOURCE.json').read_bytes()
    monkeypatch.setattr(installer.shutil, 'which', lambda _: 'git')
    def checked(argv, directory, environment, timeout):
        if '--target' in argv:
            assert 'AUTOBENCH_GIT_AUTH' not in environment
            distribution(Path(argv[argv.index('--target')+1]))
    def failed(*args):
        raise RuntimeError('gate failed')
    monkeypatch.setattr(installer, 'validate_runtime', failed)
    with pytest.raises(RuntimeError, match='gate failed'):
        installer.ensure_runtime(tmp_path, lambda: 'unit-test-token', lambda: {}, checked)
    assert (target / 'SOURCE.json').read_bytes() == original
    assert not list((tmp_path / '.bench').glob('.adcp-upgrade-*'))
    assert not list((tmp_path / '.bench').glob('adcp-backup-*'))


def test_successful_transaction_preserves_backup_and_does_not_ask_again(tmp_path, monkeypatch):
    target = tmp_path / '.bench/adcp'
    distribution(target, 'old-pin')
    monkeypatch.setattr(installer.shutil, 'which', lambda _: 'git')
    def checked(argv, directory, environment, timeout):
        if '--target' in argv:
            distribution(Path(argv[argv.index('--target')+1]))
    validations = []
    monkeypatch.setattr(installer, 'validate_runtime', lambda *args: validations.append(args[1]))
    installer.ensure_runtime(tmp_path, lambda: 'unit-test-token', lambda: {}, checked)
    assert verify_distribution(target)['commit'] == ADCP_COMMIT
    backups = list((tmp_path / '.bench').glob('adcp-backup-*'))
    assert len(backups) == 1 and json.loads((backups[0] / 'SOURCE.json').read_text())['commit'] == 'old-pin'
    def forbidden():
        raise AssertionError('Already staged runtime must not request a token')
    installer.ensure_runtime(tmp_path, forbidden, lambda: {}, checked)
    assert len(validations) == 2


def test_tampered_current_runtime_never_reaches_validation(tmp_path, monkeypatch):
    target = tmp_path / '.bench/adcp'
    distribution(target)
    (target / 'packages/zone_development/workspace.py').write_text('# tampered\n')
    def forbidden(*args):
        raise AssertionError('Tampered source must fail before execution')
    monkeypatch.setattr(installer, 'validate_runtime', forbidden)
    with pytest.raises(ValueError, match='integrity mismatch'):
        installer.ensure_runtime(tmp_path, forbidden, lambda: {}, forbidden)


def test_undeclared_python_is_not_imported(tmp_path):
    distribution(tmp_path / 'runtime')
    (tmp_path / 'runtime/extra.py').write_text('# undeclared\n')
    with pytest.raises(ValueError, match='undeclared Python'):
        verify_distribution(tmp_path / 'runtime')


def test_second_installer_cannot_race_bootstrap_or_active_campaign(tmp_path):
    from tools.launcher_lock import launcher_lock
    def forbidden(*args):
        raise AssertionError('Busy installer must not request credentials or execute')
    with launcher_lock(tmp_path / '.bench/launcher.lock'):
        with pytest.raises(RuntimeError, match='Another launcher'):
            installer.ensure_runtime(tmp_path, forbidden, forbidden, forbidden)


def test_gate_mutation_prevents_activation_and_preserves_old_runtime(tmp_path, monkeypatch):
    target = tmp_path / '.bench/adcp'
    distribution(target, 'old-pin')
    original = (target / 'SOURCE.json').read_bytes()
    monkeypatch.setattr(installer.shutil, 'which', lambda _: 'git')
    def checked(argv, directory, environment, timeout):
        if '--target' in argv:
            distribution(Path(argv[argv.index('--target')+1]))
    def mutate(root, staged, *args):
        (staged / 'packages/zone_development/workspace.py').write_bytes(b'# mutation during gate\n')
    monkeypatch.setattr(installer, 'validate_runtime', mutate)
    with pytest.raises(ValueError, match='integrity mismatch'):
        installer.ensure_runtime(tmp_path, lambda: 'unit-test-token', lambda: {}, checked)
    assert (target / 'SOURCE.json').read_bytes() == original
    assert not list((tmp_path / '.bench').glob('adcp-backup-*'))
    assert not list((tmp_path / '.bench').glob('.adcp-upgrade-*'))


def test_directory_activation_error_rolls_back_original(tmp_path, monkeypatch):
    target = tmp_path / '.bench/adcp'
    distribution(target, 'old-pin')
    original = (target / 'SOURCE.json').read_bytes()
    monkeypatch.setattr(installer.shutil, 'which', lambda _: 'git')
    def checked(argv, directory, environment, timeout):
        if '--target' in argv:
            distribution(Path(argv[argv.index('--target')+1]))
    rename = installer.os.rename
    def fail_activation(source, destination):
        if Path(source).name.startswith('.adcp-upgrade-'):
            raise OSError('activation denied')
        return rename(source, destination)
    monkeypatch.setattr(installer.os, 'rename', fail_activation)
    monkeypatch.setattr(installer, 'validate_runtime', lambda *args: None)
    with pytest.raises(OSError, match='activation denied'):
        installer.ensure_runtime(tmp_path, lambda: 'unit-test-token', lambda: {}, checked)
    assert (target / 'SOURCE.json').read_bytes() == original
    assert not list((tmp_path / '.bench').glob('.adcp-upgrade-*'))
