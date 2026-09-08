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


def outcome_diagnostic(metadata, calls):
    outcome = metadata.get('internal_outcome', {}).get('data', {})
    fields = ('type', 'phase', 'result', 'action', 'kernel_action', 'rule', 'reason_code')
    return json.dumps({'status': metadata.get('status'), 'reason': outcome.get('reason'),
        'reason_code': outcome.get('reason_code'), 'calls': calls,
        'events': [{key: event[key] for key in fields if key in event}
                   for event in metadata.get('events', ())]}, ensure_ascii=False, indent=2)


@pytest.mark.parametrize('padding_units', [16, 150000], ids=['small-repair', 'large-repair'])
def test_actual_cycle_large_snapshot_fail_repair_pass(tmp_path, padding_units):
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
                if self.codes > 1:
                    feedback = prompt.split('Public deterministic verification: ', 1)[1]
                    assert json.loads(feedback)['schema'] == 'ecacc.v2'
                after['core.py'] = 'def add(left, right):\n    return ' + ('left\n' if self.codes == 1 else 'left + right\n')
            self.invocations.append({'role': role})
            calls.append(role)
            return {'status': 'RETURNED', 'text': text, 'finish_reason': 'completed'}, after
    class ExternalTests:
        def score(self, files, checks, expected):
            # Execute the candidate, not a boolean supplied by a scripted role.
            with tempfile.TemporaryDirectory(prefix='cycle-check-') as temporary:
                write_files(Path(temporary), files)
                command = 'import runpy; f=runpy.run_path("core.py")["add"]; assert f(2,3)==5; assert f(-2,3)==1'
                result = ProcessRunner().run(CommandSpec((sys.executable, '-I', '-B', '-c', command), 20, temporary))
            calls.append('test:PASS' if result.succeeded else 'test:FAIL')
            return {'status': 'PASS' if result.succeeded else 'FAIL'}
    original = {'core.py': 'def add(left, right):\n    return left - right\n',
                'padding.py': '# ' + ('source padding ' * padding_units) + '\n', 'TASK.md': 'Fix addition'}
    if padding_units == 150000:
        # Reproduce the original codec boundary without enlarging or bypassing it.
        import shared_contracts as sc
        from packages.ecacc import SourceSnapshot
        with pytest.raises(sc.ContractError, match='Maximum wire size'):
            _ = SourceSnapshot(tuple(original.items())).content_digest
    driver = Transport()
    candidate, metadata = cycle_arm(driver, ExternalTests(), original,
        SimpleNamespace(description='Fix add: preserve its signature and return left + right.'),
        [], [], tmp_path / 'cycle', Settings())
    diagnostic = outcome_diagnostic(metadata, calls)
    print(diagnostic)
    assert 'assured_runtime' in ZoneDevelopmentRuntime.__module__
    assert metadata['status'] == 'CANDIDATE_READY', diagnostic
    assert calls == ['architect', 'coder', 'reviewer', 'test:FAIL', 'coder', 'reviewer', 'test:PASS'], diagnostic
    assert driver.codes == 2, diagnostic
    assert [event['result'] for event in metadata['events'] if event.get('phase') == 'ECACC_EVALUATED'] == ['FAIL', 'PASS']
    assert any(event.get('action') == 'REPAIR' for event in metadata['events']), diagnostic
    assert candidate['padding.py'] == original['padding.py']
    assert candidate['core.py'] == 'def add(left, right):\n    return left + right\n'
    assert metadata['verification_authority'] == 'ECACC' and metadata['controller'] == 'BADC'
