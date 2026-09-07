from dataclasses import replace
from corpus.discovery.automatic import AutomaticIntake
from corpus.qualification.policy import IssuePolicy
from corpus.discovery.issue_queries import PULLS


class Reader:
    def __init__(self, projects):
        self.projects = projects

    def search(self, query, phrase, limit):
        assert "language:Python" in phrase
        yield from [(project, "cas:repository") for project in self.projects]


def repository(name, packaged):
    return {"id": name, "nameWithOwner": name, "isPrivate": False, "isFork": False, "isArchived": False,
            "licenseInfo": {"spdxId": "MIT"}, "primaryLanguage": {"name": "Python"},
            "projectConfig": {"__typename": "Blob"} if packaged else None}


def test_automatic_search_does_not_treat_link_lists_as_python_packages():
    reader = Reader([repository("docs/list", False), repository("code/library", True)])
    intake = AutomaticIntake(reader, IssuePolicy(), 12)
    assert [row[0]["nameWithOwner"] for row in intake.repositories()] == ["code/library"]
    assert intake.rejected == [{"repository": "docs/list", "reason": "NO_CURRENT_PYTHON_PACKAGE_METADATA"}]


def test_query_retains_real_links_and_unambiguous_history_fields():
    assert "closingIssuesReferences" in PULLS
    assert "excludeUserLinked: true" in PULLS
    assert "commits(first: 1)" in PULLS
    assert "mergeCommit" in PULLS
