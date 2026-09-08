"""Real historical issue qualification with the unchanged sampler/evaluator, never an A/B result."""
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from corpus.qualification.capture import acquire_task
from corpus.qualification.policy import IssuePolicy
from corpus.qualification.qualifier import qualify
from corpus.qualification.files import text
from suites.coding.backends.native import NativeRuntime
from suites.coding.settings import Settings

REPOSITORY = 'sqlfluff/sqlfluff'
BEFORE = '5d7c04ba05e4c5612380f66eb6bb96cb9a2db4ee'
REFERENCE = '0f1037bcb2fa10b529c23c3fb95bfc3fdaaadbe5'
SEED = 1415089804296023376


def main():
    headers = {'User-Agent': 'autonomous-dev-bench-qualification/1'}
    token = os.environ.pop('GITHUB_TOKEN', None)
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request('https://api.github.com/repos/' + REPOSITORY + '/issues/8256', headers=headers)
    with urlopen(request, timeout=30) as response:
        issue = json.loads(response.read(131072))
    del request, headers, token
    for name in ('GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        os.environ.pop(name, None)
    candidate = {'repository': REPOSITORY, 'pull_number': 8411, 'pre_fix_commit': BEFORE,
                 'reference_commit': REFERENCE,
                 'issues': [{'number': 8256, 'title': issue['title'], 'body': issue['body']}]}
    report = {'scope': 'REAL_PINNED_SQLFLUFF_8411_QUALIFICATION_NOT_PAID_AB', 'status': 'FAILED',
              'platform': sys.platform, 'candidate': candidate, 'seed': SEED, 'model_called': False}
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='historical qualification ') as temporary:
        runtime = NativeRuntime(ROOT, Path(temporary), Settings())
        try:
            report['sdk'] = runtime.prepare_image()
            policy = IssuePolicy()
            started = time.monotonic()
            captured = acquire_task(candidate, ROOT, policy)
            task, prepared = qualify(ROOT, runtime, captured, policy, Settings(), SEED,
                                     time.monotonic() + policy.prepare_seconds)
            evaluator = prepared['evaluator']
            # Also require the exact plugin checks that failed for the operator; never hide them by sampling.
            plugin = evaluator.observe(captured['projection'], {'kind': 'public', 'paths': ['test/core/plugin_test.py']})
            assert plugin and set(plugin.values()) == {'PASS'}, plugin
            fixed = {**captured['projection'], **{path: text(value) for path, value in captured['fix_code'].items()}}
            empty = evaluator.score(captured['projection'], prepared['checks'], prepared['expected'])
            correct = evaluator.score(fixed, prepared['checks'], prepared['expected'])
            assert empty['status'] == 'FAIL', empty
            assert correct['status'] == 'PASS', correct
            assert runtime.relay is None
            report.update(status='PASS', wall_seconds=round(time.monotonic()-started, 3),
                          public_checks=prepared['public_checks'], qualification=prepared['qualification'],
                          plugin_checks=plugin, empty_patch=empty['status'], reference_patch=correct['status'],
                          acceptance_cases=len(prepared['expected']), sampler_changed=False,
                          synthetic_task=False, private_adcp_executed=False)
        except Exception as error:
            report['reason'] = str(error)[:2000]
            raise
        finally:
            runtime.close()
            (artifacts / 'qualification-sqlfluff.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            logs = {str(path.relative_to(runtime.scratch)): path.read_text(encoding='utf-8', errors='replace')[-20000:]
                    for path in runtime.scratch.rglob('process.log')}
            (artifacts / 'qualification-sqlfluff-logs.json').write_text(json.dumps(logs, indent=2), encoding='utf-8')
            if report['status'] != 'PASS':
                print('Historical qualification failed: ' + report.get('reason', 'UNKNOWN'), file=sys.stderr)
                for name, content in list(logs.items())[-4:]:
                    print('=== ' + name + ' ===\n' + content[-16000:], file=sys.stderr, flush=True)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
