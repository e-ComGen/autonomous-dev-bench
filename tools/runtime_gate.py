"""One-time local qualification of the actual downloaded private runtime before activation."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def gate_identity(root, distribution):
    root, distribution = Path(root), Path(distribution)
    digest = hashlib.sha256((distribution / 'SOURCE.json').read_bytes())
    for path in (root / 'tools/runtime_gate.py', root / 'tests/coding/test_runtime_upgrade.py',
                 root / 'suites/coding/cycle.py', root / 'suites/coding/cycle_roles.py',
                 root / 'suites/coding/cycle_request.py', root / 'suites/coding/public_verifier.py'):
        digest.update(path.read_bytes())
    digest.update((sys.version + sys.platform).encode())
    return digest.hexdigest()


def main():
    from suites.coding.adcp_loading import verify_distribution
    distribution = Path(sys.argv[1]).resolve()
    verify_distribution(distribution)
    identity = gate_identity(ROOT, distribution)
    report = ROOT / '.bench/runtime-validation'
    report.mkdir(parents=True, exist_ok=True)
    for name in ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        os.environ.pop(name, None)
    paths = [distribution, distribution / 'packages/shared_contracts/src', distribution / 'tests',
             ROOT / 'packages/benchmark_core', ROOT]
    sys.path[:0] = [str(path) for path in paths]
    os.environ['PYTHONPATH'] = os.pathsep.join(map(str, paths))
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['AUTOBENCH_RUNTIME_UNDER_TEST'] = str(distribution)
    os.environ.pop('PYTEST_DISABLE_PLUGIN_AUTOLOAD', None)
    suites = ['tests/zone_development', 'tests/architecture_assurance', 'tests/harness_bridge',
              'tests/ecacc', 'tests/test_badc.py', 'tests/test_adcl.py']
    for suite in suites:
        if not (distribution / suite).exists():
            raise ValueError('Private qualification suite missing: ' + suite)
    import pytest
    junit = report / (identity + '.xml')
    old = Path.cwd()
    print('Runtime gate v3: real small/large repair integration first, then original regressions', flush=True)
    try:
        os.chdir(distribution)
        with tempfile.TemporaryDirectory(prefix='adcp-gate-') as temporary:
            # Fail promptly on a broken integration; successful activation still
            # requires every original suite, with no failure/error/skip allowed.
            code = pytest.main(['-q', '--import-mode=importlib', '--maxfail=1', '-o', 'addopts=',
                '--basetemp=' + temporary, '--junitxml=' + str(junit),
                str(ROOT / 'tests/coding/test_runtime_upgrade.py'), *suites])
    finally:
        os.chdir(old)
    if code != 0 or not junit.is_file():
        raise RuntimeError('ADCP_RUNTIME_GATE_FAILED: ' + str(junit))
    tree = ET.parse(junit)
    counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
    if counts['testcase'] < 50 or counts['failure'] or counts['error'] or counts['skipped']:
        raise RuntimeError('ADCP_RUNTIME_GATE_INCOMPLETE: ' + str(junit))
    value = {'identity': identity, 'status': 'PASS', 'counts': counts, 'model_called': False,
             'junit': str(junit), 'scope': 'ACTUAL_RUNTIME_REGRESSION_NOT_PAID_AB'}
    (distribution / 'QUALIFIED.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
