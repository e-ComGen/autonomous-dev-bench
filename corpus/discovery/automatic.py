"""Seeded automatic public repository/issue intake over the existing GitHubReader."""
import random
from .github import GitHubReader, IntakeError
from .candidates import candidate, quarantine_overlaps
from .issue_queries import REPOSITORIES, PULLS, REPO
from corpus.qualification.policy import REPOSITORY


class AutomaticIntake:
    def __init__(self, reader, policy, seed):
        self.reader, self.policy = reader, policy
        self.random = random.Random(seed)
        self.rejected = []

    def repositories(self):
        policy = self.policy
        if policy.repositories:
            pool = []
            for name in policy.repositories:
                owner, repository = name.split("/", 1)
                data, receipt = self.reader.query(REPO, {"owner": owner, "name": repository})
                if isinstance(data.get("repository"), dict):
                    pool.append((data["repository"], receipt))
        else:
            # This is a seeded sample of a bounded search universe, not uniform sampling of all GitHub.
            ordering = self.random.choice(("updated-desc", "stars-desc", "stars-asc"))
            query = (f"language:Python is:public fork:false archived:false stars:{policy.min_stars}..{policy.max_stars} "
                     f"pushed:>={policy.since} sort:{ordering}")
            pool = list(self.reader.search(REPOSITORIES, query, policy.repository_pool))
        self.random.shuffle(pool)
        seen = set()
        for repository, receipt in pool:
            name = repository.get("nameWithOwner", "")
            if not REPOSITORY.fullmatch(name) or repository.get("id") in seen:
                continue
            seen.add(repository.get("id"))
            if (any(repository.get(flag) for flag in ("isPrivate", "isFork", "isArchived"))
                    or (repository.get("primaryLanguage") or {}).get("name") != "Python"
                    or (repository.get("licenseInfo") or {}).get("spdxId") not in self.policy.licenses):
                self.rejected.append({"repository": name, "reason": "REPOSITORY_FILTER"})
                continue
            yield repository, receipt

    def candidates(self):
        emitted = 0
        for index, (repository, repo_receipt) in enumerate(self.repositories()):
            if index >= self.policy.max_repositories:
                return
            name = repository["nameWithOwner"]
            query = f"repo:{name} is:pr is:merged merged:>={self.policy.since} -author:app/dependabot sort:updated-desc"
            pool = list(self.reader.search(PULLS, query, self.policy.pulls_per_repository))
            self.random.shuffle(pool)
            candidates = []
            for pull, receipt in pool:
                links = pull.get("closingIssuesReferences") or {}
                issues = links.get("nodes") or []
                if ((links.get("pageInfo") or {}).get("hasNextPage") or len(issues) != 1
                        or any((issue.get("repository") or {}).get("isPrivate")
                               or (issue.get("repository") or {}).get("nameWithOwner") != name for issue in issues)
                        or not 1 <= pull.get("changedFiles", 1000) <= 30):
                    continue
                value = candidate(repository, pull, issues, [repo_receipt, receipt])
                value["license_spdx"] = repository["licenseInfo"]["spdxId"]
                candidates.append(value)
            quarantine_overlaps(candidates)
            for value in candidates:
                if value["status"] != "NEEDS_QUALIFICATION":
                    self.rejected.append({"repository": name, "pull": value["pull_number"], "reason": ",".join(value["reasons"])})
                    continue
                emitted += 1
                yield value
                if emitted >= self.policy.max_candidates:
                    return
