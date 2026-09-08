"""Opt-in actual private runtime integration; scripted transport exists ONLY in this test."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get('AUTOBENCH_RUNTIME_UNDER_TEST'),
    reason='Actual private ADCP integration runs automatically during runtime upgrade')


def test_actual_cycle_large_snapshot_fail_repair_pass(tmp_path):
    from suites.coding.cycle import cycle_arm
    from suites.coding.settings import Settings
    from suites.coding.source import write_files
    from benchmark_core.execution import CommandSpec, ProcessRunner
    from packages.zone_development import ZoneDevelopmentRuntime
    calls = []
    class Transport:
        def __init__(self):
            self.invocations = []
            self.codes = 0
        def invoke(self, files, prompt):
            after = dict(files)
            if 'local architect' in prompt:
                role = 'architect'
                text = json.dumps({'steps': ['Correct addition without changing its interface'], 'target_paths': ['core.py']})
            elif 'Independently review' in prompt:
                role, text = 'reviewer', json.dumps({'findings': []})
            else:
                role, text = 'coder', 'Implementation applied'
                self.codes += 1
                after['core.py'] = 'def add(left, right):\n    return ' + ('left\n' if self.codes == 1 else 'left + right\n')
            self.invocations.append({'role': role})
            calls.append(role)
            return {'status': 'RETURNED', 'text': text, 'finish_reason': 'completed'}, after
    class ExternalTests:
        def score(self, files, checks, expected):
            # This executes the candidate, not a boolean supplied by the scripted role.
            with tempfile.TemporaryDirectory(prefix='cycle-check-') as temporary:
                write_files(Path(temporary), files)
                command = 'import runpy; f=runpy.run_path("core.py")["add"]; assert f(2,3)==5; assert f(-2,3)==1'
                result = ProcessRunner().run(CommandSpec((sys.executable, '-I', '-B', '-c', command), 20, temporary))
            calls.append('test:PASS' if result.succeeded else 'test:FAIL')
            return {'status': 'PASS' if result.succeeded else 'FAIL'}
    original = {'core.py': 'def add(left, right):\n    return left - right\n',
                'padding.py': '# ' + ('source padding ' * 150000) + '\n', 'TASK.md': 'Fix addition'}
    assert sum(len(text.encode()) for text in original.values()) > 1000000
    driver = Transport()
    candidate, metadata = cycle_arm(driver, ExternalTests(), original,
        SimpleNamespace(description='Fix add: preserve its signature and return left + right.'),
        [], [], tmp_path / 'cycle', Settings())
    assert 'assured_runtime' in ZoneDevelopmentRuntime.__module__
    assert metadata['status'] == 'CANDIDATE_READY', metadata
    assert driver.codes >= 2 and 'test:FAIL' in calls and 'test:PASS' in calls, calls
    assert calls.index('architect') < calls.index('coder') < calls.index('reviewer') < calls.index('test:FAIL')
    assert candidate['padding.py'] == original['padding.py']
    assert candidate['core.py'] == 'def add(left, right):\n    return left + right\n'
    assert metadata['verification_authority'] == 'ECACC' and metadata['controller'] == 'BADC'
