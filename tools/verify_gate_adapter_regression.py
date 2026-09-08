"""Run the SAME public boundary regression against exact old and current adapter bytes.

The test-only port doubles do not execute or redistribute the private runtime.
This receipt proves an adapter regression, not full ADCP or paid-model success.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = '1a16739b1718b8b8317e19107682ab5ed99e2fff'
TEST = 'tests/coding/test_gate_adapter_boundaries.py'
SELECT = 'host_verifier_uses_tree_identity_not_large_content_digest or repair_uses_ecacc_encoder_and_does_not_truncate_json'


def main():
    output = ROOT / 'artifacts'
    output.mkdir(exist_ok=True)
    observations = {}
    with tempfile.TemporaryDirectory(prefix='gate-negative-') as directory:
        for name in ('public_verifier.py', 'cycle_roles.py'):
            payload = subprocess.run(['git', 'show', BASE + ':suites/coding/' + name], cwd=ROOT,
                check=True, capture_output=True, timeout=20).stdout
            (Path(directory) / name).write_bytes(payload)
        for label, source in (('before', Path(directory)), ('after', ROOT / 'suites/coding')):
            environment = dict(os.environ, AUTOBENCH_ADAPTER_TEST_SOURCE_DIR=str(source))
            for key in ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
                environment.pop(key, None)
            junit = output / ('gate-adapter-' + label + '.xml')
            result = subprocess.run([sys.executable, '-m', 'pytest', '-q', TEST, '-k', SELECT,
                '--junitxml=' + str(junit)], cwd=ROOT, env=environment, capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=60)
            (output / ('gate-adapter-' + label + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
            tree = ET.parse(junit)
            counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
            wanted = {'testcase': 2, 'failure': 2 if label == 'before' else 0, 'error': 0, 'skipped': 0}
            if counts != wanted or result.returncode != (1 if label == 'before' else 0):
                raise RuntimeError('Adapter negative/positive control mismatch: ' + label + ': ' + str(counts))
            observations[label] = counts
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=20).stdout.strip()
    value = {'status': 'PASS', 'scope': 'PUBLIC_ADAPTER_BOUNDARIES_TEST_DOUBLES',
        'baseline': BASE, 'candidate': revision, 'platform': sys.platform, 'observations': observations,
        'private_runtime_executed': False, 'paid_model_called': False}
    (output / 'gate-adapter-regression.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
