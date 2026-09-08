"""Per-run effort allocation is not permanent repository quarantine or result reuse."""
from types import SimpleNamespace
import time
import pytest
from corpus.qualification.policy import IssuePolicy
from suites.coding.settings import Settings
import suites.coding.issue_preparation as service


@pytest.mark.parametrize('limit', [0, -1, True, 1.5, 301])
def test_preparation_quota_requires_bounded_integer(limit):
    with pytest.raises(ValueError):
        IssuePolicy(preparation_attempts_per_project=limit)


def test_quota_stops_third_expensive_attempt_but_not_other_project(tmp_path, monkeypatch):
    candidates = [{'repository': repository, 'pull_number': number, 'issues': [{'number': number}]}
                  for repository, number in [('owner/a', 1), ('owner/a', 2), ('owner/a', 3), ('owner/b', 1)]]
    intake = SimpleNamespace(rejected=[], counts={'repositories_inspected': 2, 'pulls_inspected': 4},
                             searches=[], stop_reason='SAMPLE_EXHAUSTED', candidates=lambda: iter(candidates))
    monkeypatch.setattr(service, 'GitHubReader', lambda *args: SimpleNamespace(deadline=time.monotonic()+300, requests=0))
    monkeypatch.setattr(service, 'AutomaticIntake', lambda *args: intake)
    selection = SimpleNamespace(selected=[], complete=False, deficits=lambda: {}, wants=lambda *args: True)
    monkeypatch.setattr(service, 'Selection', lambda *args: selection)
    saved = []
    def summary(report, reader, intake, selection, rejected, *args):
        saved[:] = rejected
        return {}
    monkeypatch.setattr(service, 'save_discovery', summary)
    monkeypatch.setattr(service, 'top_reasons', lambda _: 'test')
    acquired = []
    def acquire(root, candidate, *args):
        acquired.append((candidate['repository'], candidate['pull_number']))
        raise ValueError('PLATFORM_UNSUPPORTED')
    monkeypatch.setattr(service, 'acquire_bounded', acquire)
    with pytest.raises(ValueError, match='QUALIFIED_TASK_QUOTA_NOT_MET'):
        service.prepare(tmp_path, None, SimpleNamespace(cas=None), Settings(), IssuePolicy(), 17)
    assert acquired == [('owner/a', 1), ('owner/a', 2), ('owner/b', 1)]
    assert saved[2]['stage'] == 'sampling'
    assert saved[2]['reason'].startswith('PROJECT_PREPARATION_QUOTA')
    assert intake.counts['preparations_started'] == 3
