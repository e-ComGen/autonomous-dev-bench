"""Real subprocess/pytest regressions for test-root collisions; no private runtime stand-in claims."""
from pathlib import Path
import os
import pytest
from tools.runtime_gate import checked_report, gate_identity, run_phases
from tools.runtime_gate_worker import require_inputs
from .gate_layout_fixture import layout, put


def test_two_namespace_roots_collect_only_after_integration_completes(tmp_path, monkeypatch):
    root, private, events = layout(tmp_path)
    monkeypatch.setenv('GITHUB_TOKEN', 'not-a-real-token')
    result = run_phases(root, private, root / 'reports', 'layout-test', timeout=90)
    records = events.read_text().splitlines()
    assert [row.split(':')[0] for row in records] == ['integration', 'integration', 'regressions']
    assert records[0].split(':')[1] == records[1].split(':')[1]
    assert records[0].split(':')[1] != records[2].split(':')[1]
    assert result['counts'] == {'testcase': 65, 'failure': 0, 'error': 0, 'skipped': 0}
    assert set(result['phases']) == {'integration', 'regressions'}
    assert not (private / 'QUALIFIED.json').exists()
    assert 'not-a-real-token' not in ''.join(path.read_text() for path in (root / 'reports').glob('*.log'))


@pytest.mark.parametrize('verdict', ['fail', 'skip'])
def test_failed_or_skipped_integration_never_collects_regressions(tmp_path, verdict):
    root, private, events = layout(tmp_path, integration=verdict)
    with pytest.raises(RuntimeError, match='ADCP_RUNTIME_GATE_(FAILED|INCOMPLETE): integration'):
        run_phases(root, private, root / 'reports', 'blocked', timeout=90)
    assert not events.exists()
    assert not (root / 'reports/blocked.regressions.xml').exists()
    assert not (private / 'QUALIFIED.json').exists()


@pytest.mark.parametrize('verdict', ['fail', 'skip'])
def test_failed_or_skipped_original_regression_never_qualifies(tmp_path, verdict):
    root, private, events = layout(tmp_path, regression=verdict)
    with pytest.raises(RuntimeError, match='ADCP_RUNTIME_GATE_(FAILED|INCOMPLETE): regressions'):
        run_phases(root, private, root / 'reports', 'blocked', timeout=90)
    assert events.read_text().count('integration:') == 2
    assert not (root / 'reports/blocked.xml').exists()
    assert not (private / 'QUALIFIED.json').exists()


def test_missing_real_support_is_not_replaced_with_a_stub(tmp_path):
    root, private, events = layout(tmp_path)
    (private / 'tests/architecture_governance/global_support.py').unlink()
    with pytest.raises(ValueError, match='PRIVATE_GATE_INPUT_MISSING'):
        run_phases(root, private, root / 'reports', 'missing', timeout=90)
    assert not events.exists()


def test_deadline_is_shared_and_cannot_start_an_expired_phase(tmp_path):
    root, private, events = layout(tmp_path)
    with pytest.raises(RuntimeError, match='ADCP_RUNTIME_GATE_DEADLINE'):
        run_phases(root, private, root / 'reports', 'deadline', timeout=0)
    assert not events.exists()


def test_junit_requires_both_named_integration_cases(tmp_path):
    path = tmp_path / 'two.xml'
    path.write_text('<testsuites><testsuite><testcase name="wrong"/><testcase name="other"/></testsuite></testsuites>')
    with pytest.raises(RuntimeError, match='INTEGRATION_CASES_MISSING'):
        checked_report(path, 'integration')


def test_changed_worker_invalidates_previous_gate_receipt(tmp_path):
    root, private, _ = layout(tmp_path)
    put(private, 'SOURCE.json', '{}')
    for name in ('suites/coding/cycle.py', 'suites/coding/cycle_roles.py',
                 'suites/coding/cycle_request.py', 'suites/coding/public_verifier.py'):
        put(root, name, '# test identity only\n')
    before = gate_identity(root, private)
    worker = root / 'tools/runtime_gate_worker.py'
    worker.write_bytes(worker.read_bytes() + b'\n# changed identity\n')
    assert gate_identity(root, private) != before
