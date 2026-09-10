from dataclasses import replace
from pathlib import Path
import json
import pytest

from benchmark_core.cas import FileSystemCAS
from cli.oneclick.config import load_config
from corpus.discovery.candidates import candidate, quarantine_overlaps
from corpus.discovery.github import GitHubReader, IntakeError, NoRedirects

ROOT = Path(__file__).resolve().parents[2]


def example():
    return ({"id": "repo-1", "nameWithOwner": "example/project"},
            {"id": "pr-1", "number": 2, "merged": True, "createdAt": "2026-01-02T00:00:00Z",
             "headRefOid": "b" * 40, "mergeCommit": {"oid": "c" * 40,
             "parents": {"totalCount": 2, "nodes": [{"oid": "a" * 40}, {"oid": "b" * 40}]}}},
            [{"id": "issue-1", "number": 1, "title": "Incorrect response", "body": "Input produces the wrong output",
              "createdAt": "2026-01-01T00:00:00Z", "lastEditedAt": None}])


def test_candidate_never_becomes_an_admitted_task():
    item = candidate(*example(), [])
    assert item["pre_fix_commit"] == "a" * 40
    assert item["status"] == "NEEDS_QUALIFICATION"
    assert not item["qualified"] and not item["agent_ready"]


def test_edited_statement_is_quarantined():
    repo, pull, issues = example()
    issues[0]["lastEditedAt"] = "2026-01-03T00:00:00Z"
    assert "ISSUE_EDITED_AFTER_PR" in candidate(repo, pull, issues, [])["reasons"]


def test_squash_is_not_guessed():
    repo, pull, issues = example()
    pull["mergeCommit"]["parents"]["totalCount"] = 1
    item = candidate(repo, pull, issues, [])
    assert item["pre_fix_commit"] is None
    assert item["status"] == "QUARANTINED"


def test_input_mutation_does_not_change_record():
    repo, pull, issues = example()
    item = candidate(repo, pull, issues, [])
    issues[0]["body"] = "Changed"
    assert item["issues"][0]["body"] != "Changed"


def test_multiple_observed_fixes_do_not_count_as_independent_tasks():
    repo, pull, issues = example()
    first = candidate(repo, pull, issues, [])
    pull["number"] = 3
    second = candidate(repo, pull, issues, [])
    quarantine_overlaps([first, second])
    assert first["status"] == second["status"] == "QUARANTINED"


class Response:
    def __init__(self, content):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *unused):
        return False
    def read(self, size):
        return self.content[:size]


class Opener:
    def __init__(self, content):
        self.content = content
        self.calls = 0
    def open(self, request, timeout):
        self.calls += 1
        return Response(self.content)


def test_request_budget_stops_before_second_network_call(tmp_path):
    budgets = replace(load_config(ROOT / "BENCHMARK.toml").budgets, max_api_requests=1)
    opener = Opener(b'{"data":{"ok":true}}')
    reader = GitHubReader("never-store", FileSystemCAS(tmp_path), budgets, opener=opener)
    reader.query("query", {})
    with pytest.raises(IntakeError, match="BUDGET"):
        reader.query("query", {})
    assert opener.calls == 1
    assert "never-store" not in reader.cas.get_text(reader.receipts[0])


@pytest.mark.parametrize("content", [b"not-json", b'{"errors":[{"message":"error"}]}', b'{"data":null}', b'[]'])
def test_invalid_api_responses_do_not_become_receipts(tmp_path, content):
    budgets = load_config(ROOT / "BENCHMARK.toml").budgets
    reader = GitHubReader("token", FileSystemCAS(tmp_path), budgets, opener=Opener(content))
    with pytest.raises(IntakeError):
        reader.query("query", {})
    assert reader.receipts == []


def test_oversized_response_is_rejected(tmp_path):
    budgets = replace(load_config(ROOT / "BENCHMARK.toml").budgets, max_response_bytes=1024)
    reader = GitHubReader("token", FileSystemCAS(tmp_path), budgets, opener=Opener(b"x" * 1025))
    with pytest.raises(IntakeError, match="TOO_LARGE"):
        reader.query("query", {})


def test_private_transition_is_not_saved(tmp_path):
    budgets = load_config(ROOT / "BENCHMARK.toml").budgets
    reader = GitHubReader("token", FileSystemCAS(tmp_path), budgets,
                          opener=Opener(b'{"data":{"repository":{"isPrivate":true}}}'))
    with pytest.raises(IntakeError, match="PRIVATE"):
        reader.query("query", {})
    assert not reader.receipts


def test_redirect_is_never_followed():
    with pytest.raises(IntakeError, match="REDIRECT"):
        NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://foreign.invalid/")
