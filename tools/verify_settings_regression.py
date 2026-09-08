"""Run the same real-parser test against exact previous/new bytes; no model or runtime qualification."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = '75b74146b819232d38b9d57e67db590b1f6335ef'
RELATIVE = 'suites/coding/settings.py'


def git(*arguments):
    return subprocess.run(['git', '-C', str(ROOT), *arguments], check=True, capture_output=True).stdout


def main():
    source = ROOT / RELATIVE
    after = source.read_bytes()
    before = git('show', BASE + ':' + RELATIVE)
    directory = ROOT / 'artifacts'
    directory.mkdir(exist_ok=True)
    observations = {}
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'}}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        for label, content in (('before', before), ('after', after)):
            source.write_bytes(content)
            junit = directory / ('settings-' + label + '.xml')
            junit.unlink(missing_ok=True)
            executed = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q',
                'tests/coding/test_settings_compatibility.py::test_legacy_backend_matches_canonical_without_changing_budgets',
                '--junitxml=' + str(junit)], cwd=ROOT, env=environment, capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=120)
            output = executed.stdout + executed.stderr
            (directory / ('settings-' + label + '.log')).write_text(output, encoding='utf-8')
            tree = ET.parse(junit)
            counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
            expected = {'testcase': 3, 'failure': 3 if label == 'before' else 0, 'error': 0, 'skipped': 0}
            if counts != expected or executed.returncode != (1 if label == 'before' else 0):
                raise RuntimeError('Unexpected exact settings regression: ' + label + '; ' + output[-4000:])
            if label == 'before' and "Unknown A/B settings: ['backend']" not in output:
                raise RuntimeError('The supplied operator error was not reproduced')
            observations[label] = {'source_sha256': hashlib.sha256(content).hexdigest(), 'counts': counts}
    finally:
        source.write_bytes(after)
    # This is a parser/entrypoint fix, not a new private gate or authority version.
    paths = ['tools/runtime_gate.py', 'tools/runtime_gate_worker.py', 'tools/launcher_env.py',
             'tests/coding/test_runtime_upgrade.py', 'suites/coding/cycle.py',
             'suites/coding/cycle_roles.py', 'suites/coding/cycle_request.py',
             'suites/coding/public_verifier.py', 'suites/coding/adcp_loading.py']
    paths.extend(path.relative_to(ROOT).as_posix() for path in
                 sorted((ROOT / 'packages/benchmark_core/benchmark_core').rglob('*.py')))
    for name in paths:
        if (ROOT / name).read_bytes() != git('show', BASE + ':' + name):
            raise RuntimeError('Qualification-bound source changed unexpectedly: ' + name)
    report = {'status': 'PASS', 'scope': 'EXACT_SETTINGS_PARSER_REGRESSION_NOT_PAID_AB',
        'baseline': BASE, 'candidate': git('rev-parse', 'HEAD').decode().strip(),
        'platform': sys.platform, 'observations': observations,
        'qualification_bound_files_unchanged': len(paths), 'private_runtime_executed': False,
        'model_called': False, 'operator_config_rewritten': False}
    (directory / 'settings-regression.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
