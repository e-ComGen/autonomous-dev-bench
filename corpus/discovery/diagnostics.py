"""Compact discovery evidence: distinguish metadata rejection from failed builds/tests."""
from collections import Counter
import re


def reason_code(reason):
    prefix = str(reason).split(":", 1)[0].split(";", 1)[0].strip()
    return prefix if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", prefix) else "UNCLASSIFIED_ERROR"


def summarize(details, *, requested, qualified, stop_reason, counts=None, searches=None):
    stages, examples, combined = {}, [], Counter()
    for label, key in (("metadata", "intake_rejections"), ("execution", "qualification_rejections")):
        entries = details.get(key, [])
        histogram = Counter()
        for entry in entries:
            codes = [reason_code(item) for item in str(entry.get("reason", "UNKNOWN_ERROR")).split(",")]
            histogram.update(set(codes))
        combined.update(histogram)
        stages[label] = {"rejections": len(entries), "reason_counts": dict(sorted(histogram.items()))}
        # Neither issue text nor subprocess stderr belongs in the default diagnostic view.
        for entry in entries[-12:]:
            sample = {"stage": label, "repository": str(entry.get("repository", ""))[:160],
                      "reason": reason_code(entry.get("reason", "UNKNOWN_ERROR"))}
            if type(entry.get("pull")) is int:
                sample["pull"] = entry["pull"]
            examples.append(sample)
    return {"schema": "autobench.discovery_summary/v2", "requested_tasks": requested,
            "qualified": qualified, "rejections": sum(row["rejections"] for row in stages.values()),
            "stop_reason": stop_reason, "api_requests": details.get("api_requests", 0),
            "counts": dict(counts or {}), "searches": list(searches or []),
            "stages": stages, "reason_counts": dict(sorted(combined.items())),
            "examples": examples, "project_deficits": details.get("project_deficits", {})}


def top_reasons(summary, limit=4):
    rows = sorted(summary["reason_counts"].items(), key=lambda row: (-row[1], row[0]))
    return ", ".join(f"{name}={count}" for name, count in rows[:limit]) or "no_rejection_details"
