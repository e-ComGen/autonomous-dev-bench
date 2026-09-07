"""Seeded, diverse, test-aware intake over the existing bounded GitHubReader."""
from collections import deque
from itertools import islice
import random
import time
from .candidates import candidate, quarantine_overlaps
from .github import IntakeError
from .issue_queries import REPOSITORIES, PULLS, REPO
from .pull_prefilter import rejection_reason
from .search_plan import repository_searches, has_test_tree
from corpus.qualification.policy import REPOSITORY


class AutomaticIntake:
    def __init__(self, reader, policy, seed):
        self.reader, self.policy = reader, policy
        self.random = random.Random(seed)
        self.rejected, self.searches = [], []
        self.deadline = None
        self.stop_reason = "NOT_FINISHED"
        self.counts = {"repository_results": 0, "eligible_repositories": 0,
                       "repositories_inspected": 0, "pulls_inspected": 0,
                       "candidates_emitted": 0}

    def check_deadline(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stop_reason = "PREPARATION_BUDGET_EXHAUSTED"
            raise TimeoutError(self.stop_reason)

    def repositories(self):
        policy, pool = self.policy, []
        if policy.repositories:
            for name in policy.repositories:
                self.check_deadline()
                owner, repository = name.split("/", 1)
                data, receipt = self.reader.query(REPO, {"owner": owner, "name": repository})
                if isinstance(data.get("repository"), dict):
                    pool.append((data["repository"], receipt))
        else:
            for query, limit in repository_searches(policy):
                self.check_deadline()
                rows = list(self.reader.search(REPOSITORIES, query, limit))
                self.searches.append({"query": query, "limit": limit, "returned": len(rows)})
                pool.extend(rows)
        self.counts["repository_results"] = len(pool)
        self.random.shuffle(pool)
        pool.sort(key=lambda row: not has_test_tree(row[0]))
        seen = set()
        for repository, receipt in pool:
            name = repository.get("nameWithOwner", "")
            if not REPOSITORY.fullmatch(name) or repository.get("id") in seen:
                continue
            seen.add(repository.get("id"))
            if (any(repository.get(flag) for flag in ("isPrivate", "isFork", "isArchived"))
                    or (repository.get("primaryLanguage") or {}).get("name") != "Python"
                    or (repository.get("licenseInfo") or {}).get("spdxId") not in policy.licenses):
                self.rejected.append({"repository": name, "reason": "REPOSITORY_FILTER"})
                continue
            if not policy.repositories and not any(repository.get(key) for key in ("projectConfig", "setupScript", "setupConfig")):
                self.rejected.append({"repository": name, "reason": "NO_CURRENT_PYTHON_PACKAGE_METADATA"})
                continue
            self.counts["eligible_repositories"] += 1
            yield repository, receipt

    def pull_candidates(self, repository, repo_receipt):
        self.check_deadline()
        name = repository["nameWithOwner"]
        self.counts["repositories_inspected"] += 1
        query = f"repo:{name} is:pr is:merged linked:issue merged:>={self.policy.since} sort:updated-desc"
        pool = list(self.reader.search(PULLS, query, self.policy.pulls_per_repository))
        self.random.shuffle(pool)
        values, pulls, seen = [], {}, set()
        for pull, receipt in pool:
            self.check_deadline()
            if pull["id"] in seen:
                continue
            seen.add(pull["id"])
            self.counts["pulls_inspected"] += 1
            links = pull.get("closingIssuesReferences") or {}
            issues = links.get("nodes") or []
            reason = None
            if (links.get("pageInfo") or {}).get("hasNextPage") or len(issues) != 1:
                reason = "LINKED_ISSUE_NOT_UNIQUE"
            elif any((issue.get("repository") or {}).get("isPrivate")
                     or (issue.get("repository") or {}).get("nameWithOwner") != name for issue in issues):
                reason = "CROSS_REPOSITORY_OR_PRIVATE_ISSUE"
            if reason:
                self.rejected.append({"repository": name, "pull": pull["number"], "reason": reason})
                continue
            value = candidate(repository, pull, issues, [repo_receipt, receipt])
            value["license_spdx"] = repository["licenseInfo"]["spdxId"]
            values.append(value)
            pulls[value["pull_number"]] = pull
        quarantine_overlaps(values)
        accepted = deque()
        for value in values:
            reason = (",".join(value["reasons"]) if value["status"] != "NEEDS_QUALIFICATION"
                      else rejection_reason(pulls[value["pull_number"]]))
            if reason:
                self.rejected.append({"repository": name, "pull": value["pull_number"], "reason": reason})
                continue
            accepted.append(value)
        return accepted

    def candidates(self):
        pending = deque()
        try:
            for repository, receipt in islice(self.repositories(), self.policy.max_repositories):
                values = self.pull_candidates(repository, receipt)
                if not values:
                    continue
                self.counts["candidates_emitted"] += 1
                yield values.popleft()
                if self.counts["candidates_emitted"] >= self.policy.max_candidates:
                    self.stop_reason = "CANDIDATE_LIMIT"
                    return
                if values:
                    pending.append(values)
        except IntakeError as error:
            self.stop_reason = str(error)
            if str(error) != "ACQUISITION_BUDGET_EXHAUSTED" or not pending:
                raise
        while pending:
            self.check_deadline()
            values = pending.popleft()
            self.counts["candidates_emitted"] += 1
            yield values.popleft()
            if self.counts["candidates_emitted"] >= self.policy.max_candidates:
                self.stop_reason = "CANDIDATE_LIMIT"
                return
            if values:
                pending.append(values)
        if self.stop_reason == "NOT_FINISHED":
            self.stop_reason = "SEARCH_POOL_EXHAUSTED"
