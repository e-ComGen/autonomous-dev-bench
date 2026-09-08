"""Qualify both real-runtime phases without sharing pytest's import/module cache."""
from pathlib import Path
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from tools.runtime_gate_worker import require_inputs

PHASES = ('integration', 'regressions')
INTEGRATION_CASES = {
    'test_actual_cycle_large_snapshot_fail_repair_pass[small-repair]',
    'test_actual_cycle_large_snapshot_fail_repair_pass[large-repair]',
}


def require_host_runner(root=None):
    """Reject a stale or shadowed host before spending time on private tests."""
    from benchmark_core import execution
    source = Path(execution.__file__).resolve()
    if root is not None:
        expected = Path(root).resolve() / 'packages/benchmark_core/benchmark_core/execution.py'
        if source != expected:
            raise RuntimeError('ADCP_RUNTIME_GATE_HOST_SOURCE_MISMATCH: loaded=' + str(source)
                               + '; expected=' + str(expected))
    runner = execution.ProcessRunner()
    missing = [name for name in ('run', 'cancel_running') if not callable(getattr(runner, name, None))]
    if missing:
        raise RuntimeError('ADCP_RUNTIME_GATE_HOST_INCOMPATIBLE: ' + ','.join(missing)
                           + '; source=' + str(source) + '; reapply the coherent host overlay')
    return runner


def gate_identity(root, distribution):
    root, distribution = Path(root), Path(distribution)
    digest = hashlib.sha256((distribution / 'SOURCE.json').read_bytes())
    relatives = ['tools/runtime_gate.py', 'tools/runtime_gate_worker.py', 'tools/launcher_env.py',
                 'tests/coding/test_runtime_upgrade.py', 'suites/coding/cycle.py',
                 'suites/coding/cycle_roles.py', 'suites/coding/cycle_request.py',
                 'suites/coding/public_verifier.py']
    # The host process owner and its dependencies are part of qualification.
    relatives.extend(path.relative_to(root).as_posix() for path in
                     sorted((root / 'packages/benchmark_core/benchmark_core').rglob('*.py')))
    for relative in relatives:
        digest.update(relative.encode() + b'\0')
        digest.update((root / relative).read_bytes())
    digest.update((sys.version + sys.platform).encode())
    return digest.hexdigest()


def checked_report(path, phase):
    if not path.is_file():
        raise RuntimeError('ADCP_RUNTIME_GATE_REPORT_MISSING: ' + phase)
    tree = ET.parse(path)
    counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
    minimum = 2 if phase == 'integration' else 50
    if counts['testcase'] < minimum or counts['failure'] or counts['error'] or counts['skipped']:
        raise RuntimeError('ADCP_RUNTIME_GATE_INCOMPLETE: ' + phase + '; ' + str(path))
    if phase == 'integration' and (counts['testcase'] != 2 or
            {case.get('name') for case in tree.iter('testcase')} != INTEGRATION_CASES):
        raise RuntimeError('ADCP_RUNTIME_GATE_INTEGRATION_CASES_MISSING')
    return counts


def run_phases(root, distribution, report, identity, *, timeout=840):
    from benchmark_core.execution import CommandSpec
    from tools.launcher_env import clean_environment
    root, distribution, report = Path(root).resolve(), Path(distribution).resolve(), Path(report).resolve()
    runner = require_host_runner()
    require_inputs(root, distribution)
    report.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    observations = {}
    try:
        for phase in PHASES:
            junit = report / (identity + '.' + phase + '.xml')
            junit.unlink(missing_ok=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('ADCP_RUNTIME_GATE_DEADLINE: ' + phase)
            execution = runner.run(CommandSpec((sys.executable, '-I', '-B',
                str(root / 'tools/runtime_gate_worker.py'), str(distribution), phase, str(junit)),
                remaining, str(distribution), clean_environment(root), inherit_environment=False))
            log = report / (identity + '.' + phase + '.log')
            log.write_text(execution.stdout[-65536:] + execution.stderr[-65536:], encoding='utf-8')
            print(execution.stdout[-65536:], end='', flush=True)
            print(execution.stderr[-65536:], end='', file=sys.stderr, flush=True)
            if not execution.succeeded:
                raise RuntimeError('ADCP_RUNTIME_GATE_FAILED: ' + phase + '; ' + str(log))
            counts = checked_report(junit, phase)
            observations[phase] = {'counts': counts, 'junit': str(junit), 'log': str(log)}
            print('Runtime gate v4: ' + phase + ' PASS', flush=True)
    finally:
        runner.cancel_running()
    # Keep the existing single-JUnit artifact, retaining every original test case.
    combined = ET.Element('testsuites')
    for phase in PHASES:
        tree = ET.parse(observations[phase]['junit']).getroot()
        combined.extend(list(tree) if tree.tag == 'testsuites' else [tree])
    junit = report / (identity + '.xml')
    ET.ElementTree(combined).write(junit, encoding='utf-8', xml_declaration=True)
    counts = {tag: sum(item['counts'][tag] for item in observations.values())
              for tag in ('testcase', 'failure', 'error', 'skipped')}
    return {'counts': counts, 'phases': observations, 'junit': str(junit)}


def main():
    from suites.coding.adcp_loading import verify_distribution
    require_host_runner(ROOT)
    print('Runtime: host-api-v1; local ProcessRunner run/cancel_running verified', flush=True)
    distribution = Path(sys.argv[1]).resolve()
    verify_distribution(distribution)
    identity = gate_identity(ROOT, distribution)
    marker = distribution / 'QUALIFIED.json'
    marker.unlink(missing_ok=True)
    print('Runtime gate v4: independent pytest processes; integration completes before regression collection', flush=True)
    result = run_phases(ROOT, distribution, ROOT / '.bench/runtime-validation', identity)
    verify_distribution(distribution)
    if gate_identity(ROOT, distribution) != identity:
        raise RuntimeError('ADCP_RUNTIME_GATE_SOURCE_CHANGED')
    value = {'identity': identity, 'status': 'PASS', **result, 'gate_version': 4,
             'host_api_checked': True, 'model_called': False,
             'scope': 'ACTUAL_RUNTIME_REGRESSION_NOT_PAID_AB'}
    marker.write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
