"""Real SQLFluff environment regression, preserving the seeded full-qualification rejection."""
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from corpus.qualification.capture import acquire_task
from corpus.qualification.policy import IssuePolicy
from corpus.qualification.qualifier import qualify
from corpus.qualification.files import text, is_pytest_module
from corpus.qualification.evaluator import PytestEvaluator
from corpus.qualification.junit import parse_junit, acceptance_sets
from suites.coding.backends.native import NativeRuntime
from suites.coding.settings import Settings

REPOSITORY = 'sqlfluff/sqlfluff'
BEFORE = '5d7c04ba05e4c5612380f66eb6bb96cb9a2db4ee'
REFERENCE = '0f1037bcb2fa10b529c23c3fb95bfc3fdaaadbe5'
SEED = 1415089804296023376


class ObservedRuntime(NativeRuntime):
    """Test instrumentation only: retain the actual build result, never substitute it."""
    def build_project_environment(self, task, policy, deadline):
        self.built = super().build_project_environment(task, policy, deadline)
        return self.built


def seeded_admission(runtime, captured, policy, artifacts):
    try:
        qualify(ROOT, runtime, captured, policy, Settings(), SEED, time.monotonic() + policy.prepare_seconds)
    except ValueError as error:
        if str(error) != 'PUBLIC_BASELINE_NOT_GREEN':
            raise
        # The chosen public baseline has optional-environment skips. Preserve them as
        # a rejected full task, not a passing benchmark or a reduced replacement suite.
        reports = list(runtime.scratch.rglob('results/tests.xml'))
        if len(reports) != 1:
            raise ValueError('Unexpected full-qualification observation count') from error
        payload = reports[0].read_bytes()
        observations = parse_junit(payload)
        if set(observations.values()) != {'PASS', 'SKIP'}:
            raise ValueError('Seeded rejection contains errors/failures, not only skips') from error
        skipped = [{'case': case.get('classname', '') + '::' + case.get('name', ''),
                    'reason': case.find('skipped').get('message', '')}
                   for case in ET.fromstring(payload).iter('testcase') if case.find('skipped') is not None]
        shutil.copyfile(reports[0], artifacts / 'qualification-sqlfluff-public.xml')
        return {'status': 'REJECTED', 'reason': str(error), 'observed': observations,
                'skipped': skipped, 'passed': sum(value == 'PASS' for value in observations.values()),
                'tests_removed': False, 'sampler_overridden': False}
    raise ValueError('Expected the declared seeded skip-boundary control to reject this task')


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
    report = {'scope': 'REAL_SQLFLUFF_PLUGIN_AND_REFERENCE_REGRESSION_NOT_FULL_TASK_OR_PAID_AB',
              'status': 'FAILED', 'task_qualified': False, 'platform': sys.platform,
              'candidate': candidate, 'seed': SEED, 'model_called': False}
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='historical qualification ') as temporary:
        runtime = ObservedRuntime(ROOT, Path(temporary), Settings())
        try:
            report['sdk'] = runtime.prepare_image()
            policy = IssuePolicy()
            captured = acquire_task(candidate, ROOT, policy)
            report['full_qualification'] = seeded_admission(runtime, captured, policy, artifacts)
            image, recipe = runtime.built
            evaluator = PytestEvaluator(runtime, ROOT, runtime.scratch / 'targeted-checks', captured, image, 120)
            public = {'kind': 'public', 'paths': ['test/core/plugin_test.py']}
            hidden = {'kind': 'acceptance', 'paths': sorted(name for name in captured['test_overlay'] if is_pytest_module(name))}
            base = captured['projection']
            fixed = {**base, **{name: text(value) for name, value in captured['fix_code'].items()}}
            samples = []
            for _ in range(policy.qualification_repeats):
                plugin = evaluator.observe(base, public)
                broken = evaluator.observe(base, hidden)
                repaired = evaluator.observe(fixed, hidden)
                sets = acceptance_sets(plugin, broken, repaired)
                fixed_plugin = evaluator.observe(fixed, public)
                if plugin != fixed_plugin:
                    raise ValueError('Reference altered plugin results')
                samples.append((plugin, broken, repaired, fixed_plugin))
            if any(sample != samples[0] for sample in samples[1:]):
                raise ValueError('Nondeterministic targeted observations')
            combined = {'kind': 'acceptance', 'paths': sorted(set(public['paths'] + hidden['paths']))}
            expected = evaluator.observe(fixed, combined)
            if set(expected.values()) != {'PASS'}:
                raise ValueError('Targeted combined reference did not pass')
            empty, correct = evaluator.score(base, combined, expected), evaluator.score(fixed, combined, expected)
            if empty['status'] != 'FAIL' or correct['status'] != 'PASS' or runtime.relay is not None:
                raise ValueError('Targeted empty/reference controls failed')
            report.update(status='CHECKED', image=image, recipe=recipe, plugin_checks=plugin,
                          targeted_fail_to_pass=sets['fail_to_pass'], targeted_cases=len(expected),
                          repeats=policy.qualification_repeats, empty_patch=empty['status'],
                          reference_patch=correct['status'], private_adcp_executed=False)
        except Exception as error:
            report['reason'] = str(error)[:2000]
            raise
        finally:
            runtime.close()
            (artifacts / 'qualification-sqlfluff.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            logs = {str(path.relative_to(runtime.scratch)): path.read_text(encoding='utf-8', errors='replace')[-20000:]
                    for path in runtime.scratch.rglob('process.log')}
            (artifacts / 'qualification-sqlfluff-logs.json').write_text(json.dumps(logs, indent=2), encoding='utf-8')
            if report['status'] != 'CHECKED':
                for name, content in list(logs.items())[-4:]:
                    print('=== ' + name + ' ===\n' + content[-16000:], file=sys.stderr, flush=True)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
