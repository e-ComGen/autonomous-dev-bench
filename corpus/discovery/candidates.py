"""Conservative source/statement binding; all output remains evaluator-only."""
from datetime import datetime
from benchmark_core.identity import CommitPin, Sha256Digest


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timezone")
    return parsed


def candidate(repository, pull, issues, receipts):
    reasons = []
    merge = pull.get("mergeCommit") or {}
    connection = merge.get("parents") or {}
    parents = connection.get("nodes") or []
    base = None
    merge_sha = None
    try:
        merge_sha = str(CommitPin(merge["oid"]))
        if connection.get("totalCount") == 2 and len(parents) == 2 and parents[1]["oid"] == pull["headRefOid"]:
            base = str(CommitPin(parents[0]["oid"]))
        else:
            reasons.append("HISTORY_RECONSTRUCTION_REQUIRED")
    except (KeyError, ValueError, TypeError):
        reasons.append("COMMIT_BINDING_UNAVAILABLE")
    if not pull.get("merged"):
        reasons.append("NOT_MERGED")
    snapshots = []
    for issue in issues:
        value = {key: issue.get(key) for key in ("id", "number", "title", "body", "createdAt", "lastEditedAt")}
        if not isinstance(value["body"], str) or not value["body"].strip():
            reasons.append("EMPTY_STATEMENT")
        try:
            created = timestamp(pull["createdAt"])
            if timestamp(value["createdAt"]) > created:
                reasons.append("ISSUE_CREATED_AFTER_PR")
            if value["lastEditedAt"] and timestamp(value["lastEditedAt"]) > created:
                reasons.append("ISSUE_EDITED_AFTER_PR")
        except (KeyError, ValueError, TypeError):
            reasons.append("CHRONOLOGY_UNVERIFIED")
        snapshots.append(value)
    if not snapshots:
        reasons.append("NO_LINKED_ISSUES")
    identity = {"repository_id": repository["id"], "pull_id": pull["id"],
                "base": base, "merge": merge_sha, "statements": snapshots}
    return {"schema": "autobench.candidate/v1", "candidate_id": str(Sha256Digest.of(identity)),
            "repository": repository["nameWithOwner"], "repository_id": repository["id"],
            "pull_number": pull["number"], "pre_fix_commit": base, "reference_commit": merge_sha,
            "issues": snapshots, "provenance_refs": list(receipts),
            "status": "QUARANTINED" if reasons else "NEEDS_QUALIFICATION",
            "qualified": False, "agent_ready": False, "visibility": "EVALUATOR_ONLY",
            "contamination_review": "NOT_PERFORMED", "reasons": sorted(set(reasons))}


def quarantine_overlaps(candidates):
    owners = {}
    for item in candidates:
        for issue in item["issues"]:
            owners.setdefault((item["repository_id"], issue["id"]), set()).add(item["pull_number"])
    for item in candidates:
        if any(len(owners[(item["repository_id"], issue["id"])]) > 1 for issue in item["issues"]):
            item["status"] = "QUARANTINED"
            item["reasons"] = sorted(set(item["reasons"] + ["MULTIPLE_OBSERVED_FIXES"]))
