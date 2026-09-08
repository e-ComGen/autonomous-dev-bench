"""Host ABI, real gate finalization and coherent overlays; synthetic private layout only."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import pytest
from tools.runtime_gate import gate_identity, require_host_runner, run_phases
from tools.package_native_completion import overlay_names

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('host_gate_layout_fixture', Path(__file__).with_name('gate_layout_fixture.py'))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
layout, put = _fixture.layout, _fixture.put


def executable_layout(tmp_path, **kwargs):
    root, private, events = layout(tmp_path, **kwargs)
    shutil.copytree(ROOT / 'packages/benchmark_core', root / 'packages/benchmark_core',
                    ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    for name in ('suites/coding/adcp_loading.py', 'suites/coding/cycle.py',
                 'suites/coding/cycle_roles.py', 'suites/coding/cycle_request.py',
                 'suites/coding/public_verifier.py'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    from suites.coding.adcp_loading import ADCP_COMMIT
    for name in ('contracts.py', 'workspace.py', 'snapshot_reader.py'):
        put(private, 'packages/zone_development/' + name, '# Synthetic layout ONLY; no private implementation.\n')
    files = {path.relative_to(private).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in private.rglob('*') if path.is_file()}
    put(private, 'SOURCE.json', json.dumps({'commit': ADCP_COMMIT, 'files': files}))
    return root, private, events


def invoke_gate(root, private):
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'PYTHONPATH'}}
    environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    return subprocess.run([sys.executable, '-I', '-B', str(root / 'tools/runtime_gate.py'), str(private)],
                          cwd=root, env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=90)


def test_coherent_overlay_includes_unchanged_core_and_all_host_sources():
    names = ['packages/benchmark_core/benchmark_core/execution.py', 'tools/runtime_gate.py',
             'suites/coding/public_verifier.py', 'corpus/projects/a.json', 'START.cmd',
             'AB.toml', 'BENCHMARK.toml', 'benchmark.lock', '.env', '.env.example',
             '.bench/adcp/SOURCE.json', 'vendor/wheels/x.whl']
    selected = overlay_names(names, names[1:])
    assert selected == sorted(names[:5])


def test_existing_process_owner_remains_real_and_locally_bound():
    runner = require_host_runner(ROOT)
    from benchmark_core.execution import CommandSpec
    result = runner.run(CommandSpec((sys.executable, '-I', '-c', 'print("host-ok")'), 10))
    assert result.succeeded and result.stdout.strip() == 'host-ok'
    runner.cancel_running()


def test_foreign_module_location_is_not_accepted(tmp_path):
    with pytest.raises(RuntimeError, match='HOST_SOURCE_MISMATCH'):
        require_host_runner(tmp_path)


def test_missing_cleanup_api_fails_before_any_phase(tmp_path, monkeypatch):
    root, private, events = layout(tmp_path)
    import benchmark_core.execution as execution
    class OldABI:
        def run(self, *args, **kwargs):
            raise AssertionError('No private test process may start with an incompatible host')
    monkeypatch.setattr(execution, 'ProcessRunner', OldABI)
    with pytest.raises(RuntimeError, match='HOST_INCOMPATIBLE: cancel_running'):
        run_phases(root, private, root / 'reports', 'incompatible')
    assert not events.exists()
    assert not (private / 'QUALIFIED.json').exists()


def test_actual_gate_main_reaches_receipt_after_cleanup(tmp_path):
    root, private, events = executable_layout(tmp_path)
    result = invoke_gate(root, private)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((private / 'QUALIFIED.json').read_text())
    assert receipt['status'] == 'PASS' and receipt['host_api_checked']
    assert receipt['identity'] == gate_identity(root, private)
    assert receipt['counts'] == {'testcase': 65, 'failure': 0, 'error': 0, 'skipped': 0}
    assert Path(receipt['junit']).is_file()
    assert 'regressions PASS' in result.stdout
    assert events.read_text().count('integration:') == 2


def test_actual_gate_main_rejects_old_local_core_before_tests(tmp_path):
    root, private, events = executable_layout(tmp_path)
    source = root / 'packages/benchmark_core/benchmark_core/execution.py'
    content = source.read_text(encoding='utf-8')
    assert 'def cancel_running(self):' in content
    # Inject exactly the missing API shape, never a production replacement.
    source.write_text(content.replace('def cancel_running(self):', 'def removed_cleanup(self):', 1), encoding='utf-8')
    result = invoke_gate(root, private)
    assert result.returncode != 0
    assert 'HOST_INCOMPATIBLE: cancel_running' in result.stderr
    assert not events.exists()
    assert not (private / 'QUALIFIED.json').exists()


@pytest.mark.parametrize('phase', ['integration', 'regression'])
def test_gate_main_cannot_write_receipt_for_a_failed_phase(tmp_path, phase):
    root, private, _ = executable_layout(tmp_path, **{phase: 'fail'})
    result = invoke_gate(root, private)
    assert result.returncode != 0
    assert 'ADCP_RUNTIME_GATE_FAILED:' in result.stderr
    assert not (private / 'QUALIFIED.json').exists()


def test_core_source_change_invalidates_qualification_identity(tmp_path):
    root, private, _ = executable_layout(tmp_path)
    before = gate_identity(root, private)
    path = root / 'packages/benchmark_core/benchmark_core/execution.py'
    path.write_bytes(path.read_bytes() + b'\n# changed host bytes\n')
    assert gate_identity(root, private) != before
