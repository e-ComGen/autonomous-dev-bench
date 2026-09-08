"""Runtime-start reporting tests; only the external installation body is replaced."""
import json
import pytest
from cli.oneclick.report import Report
from tools.launcher_lock import launcher_lock
import tools.runtime_install as installer


def latest(root):
    pointer = json.loads((root / '.bench/latest.json').read_text())
    return pointer, json.loads((root / pointer['report']).read_text())


def test_gate_failure_replaces_stale_latest_pointer_without_deleting_old_report(tmp_path, monkeypatch):
    old = Report(tmp_path, 'ab').save({'status': 'AB_INCOMPLETE', 'reason': 'old-discovery'})
    old_bytes = old.read_bytes()
    def fail(*args):
        raise RuntimeError('ADCP_RUNTIME_GATE_FAILED: diagnostic.log')
    monkeypatch.setattr(installer, '_ensure_runtime', fail)
    with pytest.raises(RuntimeError, match='ADCP_RUNTIME_GATE_FAILED'):
        installer.ensure_runtime(tmp_path, None, None, None)
    pointer, report = latest(tmp_path)
    assert pointer['command'] == 'runtime-upgrade' and report['status'] == 'BLOCKED'
    assert report['phase'] == 'RUNTIME_UPGRADE' and report['live_model_called'] is False
    assert report['reason'].startswith('ADCP_RUNTIME_GATE_FAILED') and report['rows'] == []
    assert old.read_bytes() == old_bytes


def test_busy_runtime_does_not_replace_active_report(tmp_path):
    Report(tmp_path, 'ab').save({'status': 'RUNNING'})
    previous = (tmp_path / '.bench/latest.json').read_bytes()
    with launcher_lock(tmp_path / '.bench/launcher.lock'):
        with pytest.raises(RuntimeError, match='Another launcher'):
            installer.ensure_runtime(tmp_path, None, None, None)
    assert (tmp_path / '.bench/latest.json').read_bytes() == previous


def test_cancelled_runtime_is_not_an_ab_success(tmp_path, monkeypatch):
    def cancel(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(installer, '_ensure_runtime', cancel)
    with pytest.raises(KeyboardInterrupt):
        installer.ensure_runtime(tmp_path, None, None, None)
    _, report = latest(tmp_path)
    assert report['status'] == 'CANCELLED' and not report['live_model_called']
