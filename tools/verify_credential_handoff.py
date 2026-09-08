"""Exact-entrypoint regression and packaged launcher probes; never a paid A/B result."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'e7d64f4e114c0b470924b235b5efb34969baec5a'
CHANGED = ('tools/bench.py', 'tools/launch.py')


def git(*arguments):
    return subprocess.run(['git', '-C', str(ROOT), *arguments], check=True, capture_output=True).stdout


def regression():
    after = {name: (ROOT / name).read_bytes() for name in CHANGED}
    before = {name: git('show', BASE + ':' + name) for name in CHANGED}
    destination = ROOT / 'artifacts'
    destination.mkdir(exist_ok=True)
    observations = {}
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'}}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        for label, contents in (('before', before), ('after', after)):
            for name, content in contents.items():
                (ROOT / name).write_bytes(content)
            junit = destination / ('credential-' + label + '.xml')
            junit.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q',
                'tests/oneclick/test_host_credentials.py::test_actual_bench_ab_retains_both_provider_boundaries',
                '--junitxml=' + str(junit)], cwd=ROOT, env=environment,
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            output = result.stdout + result.stderr
            (destination / ('credential-' + label + '.log')).write_text(output, encoding='utf-8')
            tree = ET.parse(junit)
            counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
            expected = {'testcase': 4, 'failure': 4 if label == 'before' else 0, 'error': 0, 'skipped': 0}
            if counts != expected or result.returncode != (1 if label == 'before' else 0):
                raise RuntimeError('Unexpected credential regression: ' + label + '; ' + output[-4000:])
            if label == 'before' and 'GITHUB_TOKEN_MISSING' not in output:
                raise RuntimeError('The observed operator failure was not reproduced')
            observations[label] = {'counts': counts,
                'source_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}}
    finally:
        for name, content in after.items():
            (ROOT / name).write_bytes(content)
    report = {'status': 'PASS', 'scope': 'EXACT_HOST_ENTRYPOINT_REGRESSION_NOT_PAID_AB',
        'baseline': BASE, 'candidate': git('rev-parse', 'HEAD').decode().strip(),
        'platform': sys.platform, 'observations': observations,
        'private_runtime_executed': False, 'model_called': False, 'github_requests': 0}
    (destination / 'credential-regression.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


def packaged():
    spec = importlib.util.spec_from_file_location('credential_probe_fixture', ROOT / 'tests/oneclick/credential_probe_fixture.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    source = ROOT / 'artifacts/autobenchmark'
    observations = []
    with tempfile.TemporaryDirectory(prefix='credential chain with spaces ') as temporary:
        root = fixture.populate(Path(temporary) / 'benchmark', source, wheels=True)
        originals = {name: (root / name).read_bytes() for name in CHANGED}
        config = (root / 'AB.toml').read_bytes()
        cases = [('ab', 'dotenv'), ('ab', 'environment-alias'), ('ab-preflight', 'dotenv-alias'),
                 ('qualify', 'dotenv'), ('discover', 'environment-alias'), ('test', 'dotenv'),
                 ('help', 'environment')]
        for command, source_kind in cases:
            environment = fixture.credentials(root, source_kind)
            arguments = ['ab', '--help'] if command == 'help' else [command]
            if command in {'help', 'test'}:
                (root / '.env').write_text('GITHUB_TOKEN="unterminated\n', encoding='utf-8')
            original_credentials = (root / '.env').read_bytes()
            observed = fixture.invoke(root, arguments, environment, full_chain=True)
            acquisition = command in {'ab', 'ab-preflight', 'qualify', 'discover'}
            if observed['host']['GITHUB_TOKEN'] != acquisition:
                raise RuntimeError('PACKAGED_HOST_GITHUB_SCOPE_FAILED: ' + command)
            if observed['host']['DEEPSEEK_API_KEY'] != (command == 'ab'):
                raise RuntimeError('PACKAGED_HOST_PROVIDER_SCOPE_FAILED: ' + command)
            if acquisition and (observed['github_error'] or not observed['github_matches']):
                raise RuntimeError('PACKAGED_GITHUB_ADMISSION_FAILED: ' + command)
            if command == 'ab' and (observed['provider_error'] or not observed['provider_matches']):
                raise RuntimeError('PACKAGED_MODEL_ADMISSION_FAILED')
            if observed['api_requests'] or observed['model_called']:
                raise RuntimeError('PACKAGED_PROBE_MUST_NOT_CALL_NETWORK_OR_MODEL')
            if observed['host']['OPENAI_API_KEY'] or observed['host']['OTHER_SECRET']:
                raise RuntimeError('PACKAGED_UNRELATED_CREDENTIAL_FORWARDED')
            if any(any(values.values()) for values in observed['children'].values()):
                raise RuntimeError('PACKAGED_WORKER_CREDENTIAL_LEAK')
            if (root / '.env').read_bytes() != original_credentials or (root / 'AB.toml').read_bytes() != config:
                raise RuntimeError('PACKAGED_OPERATOR_CONFIG_CHANGED')
            observations.append({'mode': command, 'credential_source': source_kind, **observed})
        if any((root / name).read_bytes() != original for name, original in originals.items()):
            raise RuntimeError('PACKAGED_ENTRYPOINT_BYTES_CHANGED')
        if not list((root / '.bench').glob('runtime-*/.ready')) or (root / '.git').exists():
            raise RuntimeError('PACKAGED_PROBE_REQUIRES_REAL_BOOTSTRAP_AND_NO_GIT')
    report = {'status': 'PASS', 'scope': 'PACKAGED_START_TO_BENCH_WITH_TEST_ONLY_TERMINAL_PROBES',
        'platform': sys.platform, 'actual_batch': os.name == 'nt', 'path_with_spaces': True,
        'genuine_launcher_venv': True, 'verified_bundled_wheels': True,
        'entrypoints_unmodified_in_fixture': list(CHANGED), 'observations': observations,
        'private_runtime_executed': False, 'model_called': False, 'github_requests': 0}
    destination = ROOT / 'artifacts/release-evidence'
    destination.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2)
    (destination / 'credential-chain.json').write_text(content, encoding='utf-8')
    # Overlay receipts do not change the complete release's source hash inventory.
    (ROOT / 'artifacts/completion-fix/CREDENTIAL_CHAIN_VALIDATION.json').write_text(content, encoding='utf-8')
    print(content)


if __name__ == '__main__':
    if sys.argv[1:] == ['--packaged']:
        packaged()
    elif not sys.argv[1:]:
        regression()
    else:
        raise SystemExit('Expected --packaged or no arguments')
