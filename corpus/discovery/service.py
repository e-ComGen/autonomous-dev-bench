"""Search -> bound candidates -> CAS. This stage never executes repository code."""
from collections import Counter
import os
import re

from benchmark_core.identity import canonical_json
from . import queries
from .candidates import candidate, quarantine_overlaps
from .github import GitHubReader, IntakeError


def collect(config, cas, *, reader=None):
    reader = reader or GitHubReader(os.environ.get("GITHUB_TOKEN"), cas, config.budgets)
    settings = config.discovery
    candidates, repositories, rejections = [], [], Counter()
    stop = None
    search = (f"language:{settings.language} stars:>={settings.min_stars} "
              "is:public fork:false archived:false sort:updated-desc")
    try:
        for repository, repo_receipt in reader.search(queries.REPOSITORIES, search, settings.max_repositories):
            name = repository.get("nameWithOwner", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
                raise IntakeError("INVALID_REPOSITORY_NAME")
            if any(repository.get(key) for key in ("isPrivate", "isFork", "isArchived")):
                rejections["REPOSITORY_FILTER"] += 1
                continue
            if (repository.get("licenseInfo") or {}).get("spdxId") not in settings.licenses:
                rejections["LICENSE_FILTER"] += 1
                continue
            repositories.append(name)
            owner, project = name.split("/", 1)
            query = f"repo:{name} is:pr is:merged merged:>={settings.since} sort:updated-desc"
            for pull, pull_receipt in reader.search(queries.PULLS, query, settings.max_prs_per_repository):
                links = pull.get("closingIssuesReferences") or {}
                issues = links.get("nodes") or []
                if (links.get("pageInfo") or {}).get("hasNextPage"):
                    rejections["TRUNCATED_ISSUE_LINKS"] += 1
                    continue
                if not issues:
                    rejections["NO_LINKED_ISSUES"] += 1
                    continue
                if any((issue.get("repository") or {}).get("nameWithOwner") != name
                       or (issue.get("repository") or {}).get("isPrivate") for issue in issues):
                    rejections["CROSS_REPOSITORY_OR_PRIVATE_ISSUES"] += 1
                    continue
                statements, receipts = [], [repo_receipt, pull_receipt]
                for issue in issues:
                    data, receipt = reader.query(queries.ISSUE, {"owner": owner, "name": project, "number": issue["number"]})
                    statement = (data.get("repository") or {}).get("issue")
                    if not isinstance(statement, dict):
                        raise IntakeError("ISSUE_UNAVAILABLE")
                    statements.append(statement)
                    receipts.append(receipt)
                candidates.append(candidate(repository, pull, statements, receipts))
    except IntakeError as error:
        stop = str(error)
    quarantine_overlaps(candidates)
    references = [cas.put_text(canonical_json(item)) for item in candidates]
    index_ref = cas.put_text(canonical_json({"candidates": references, "receipts": reader.receipts}))
    return {"status": "PARTIAL" if stop else "COLLECTED_UNQUALIFIED", "stop_reason": stop,
            "candidate_count": len(candidates), "quarantined": sum(item["status"] == "QUARANTINED" for item in candidates),
            "repositories": repositories, "rejections": dict(rejections), "index_ref": index_ref,
            "qualified_coding_tasks": 0, "api_requests": reader.requests,
            "selection_is_bounded_sample": True, "deadline_semantics": "REQUEST_ADMISSION_ONLY",
            "visibility": "EVALUATOR_ONLY"}
