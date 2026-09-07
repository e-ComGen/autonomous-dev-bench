from dataclasses import replace
from types import SimpleNamespace
from copy import deepcopy
import time
import pytest
from corpus.discovery.automatic import AutomaticIntake
from corpus.discovery.issue_queries import PULLS, REPO
from corpus.discovery.search_plan import repository_searches
from corpus.qualification.policy import IssuePolicy


def repository(name):
    return {"id": name, "nameWithOwner": name, "isPrivate": False, "isFork": False,
            "isArchived": False, "primaryLanguage": {"name": "Python"},
            "licenseInfo": {"spdxId": "MIT"}, "projectConfig": {"__typename": "Blob"}}


def candidate_pull(name, number, tested=True):
    issue = {"id": f"issue-{name}-{number}", "number": number, "title": "Problem", "body": "Expected behavior fails.",
             "createdAt": "2023-01-01T00:00:00Z", "lastEditedAt": None,
             "repository": {"nameWithOwner": name, "isPrivate": False}}
    files = [{"path": "package/core.py", "changeType": "MODIFIED"}]
    if tested:
        files.append({"path": "tests/test_core.py", "changeType": "ADDED"})
    return {"id": f"pull-{name}-{number}", "number": number, "merged": True,
            "createdAt": "2023-01-02T00:00:00Z", "headRefOid": "b" * 40,
            "mergeCommit": {"oid": "c" * 40, "parents": {"totalCount": 2,
                              "nodes": [{"oid": "a" * 40}, {"oid": "b" * 40}]}},
            "changedFiles": len(files), "files": {"totalCount": len(files), "nodes": files, "pageInfo": {"hasNextPage": False}},
            "closingIssuesReferences": {"nodes": [issue], "pageInfo": {"hasNextPage": False}}}


class Reader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def query(self, document, variables):
        assert document == REPO
        name = variables["owner"] + "/" + variables["name"]
        return {"repository": repository(name)}, "cas:repo"

    def search(self, document, query, limit):
        self.calls.append((document, query, limit))
        assert document == PULLS
        name = query.split()[0].removeprefix("repo:")
        for value in self.rows[name][:limit]:
            yield deepcopy(value), "cas:pull"


def test_all_bands_fit_existing_budget_and_filters():
    policy = IssuePolicy()
    searches = repository_searches(policy)
    assert sum(limit for _, limit in searches) == policy.repository_pool
    assert len(searches) == 3
    assert all("stars-asc" not in query and "language:Python" in query for query, _ in searches)
    narrow = SimpleNamespace(min_stars=2500, max_stars=3000, repository_pool=9, since="2022-01-01")
    assert len(repository_searches(narrow)) == 1
    assert "stars:2500..3000" in repository_searches(narrow)[0][0]


def test_no_test_pull_does_not_consume_download_candidate_budget():
    name = "example/package"
    policy = replace(IssuePolicy(), repositories=(name,), max_candidates=1)
    rows = [candidate_pull(name, number, tested=False) for number in range(1, 12)]
    reader = Reader({name: rows + [candidate_pull(name, 20)]})
    intake = AutomaticIntake(reader, policy, 123)
    selected = list(intake.candidates())
    assert [value["pull_number"] for value in selected] == [20]
    assert intake.counts["candidates_emitted"] == 1
    assert len(intake.rejected) == 11
    assert all(value["qualified"] is False and value["agent_ready"] is False for value in selected)


def test_distinct_repositories_precede_second_candidate_from_same_repository():
    names = ("example/one", "example/two", "example/three")
    policy = replace(IssuePolicy(), repositories=names, max_candidates=4)
    rows = {name: [candidate_pull(name, 1), candidate_pull(name, 2)] for name in names}
    first = list(AutomaticIntake(Reader(rows), policy, 42).candidates())
    second = list(AutomaticIntake(Reader(rows), policy, 42).candidates())
    assert first == second and len(first) == 4
    assert len({value["repository"] for value in first[:3]}) == 3


def test_historical_statement_gates_are_not_bypassed_by_test_metadata():
    name = "example/package"
    value = candidate_pull(name, 1)
    value["closingIssuesReferences"]["nodes"][0]["lastEditedAt"] = "2023-01-03T00:00:00Z"
    intake = AutomaticIntake(Reader({name: [value]}), replace(IssuePolicy(), repositories=(name,)), 1)
    assert list(intake.candidates()) == []
    assert intake.rejected[0]["reason"] == "ISSUE_EDITED_AFTER_PR"


def test_deadline_does_not_issue_more_requests():
    intake = AutomaticIntake(Reader({}), IssuePolicy(), 1)
    intake.deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="PREPARATION_BUDGET_EXHAUSTED"):
        list(intake.candidates())
    assert not intake.reader.calls
