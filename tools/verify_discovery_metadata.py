"""Live automatic GraphQL intake; metadata admission is NOT executable qualification."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from benchmark_core.cas import FileSystemCAS
from corpus.discovery.automatic import AutomaticIntake
from corpus.discovery.github import GitHubReader
from corpus.discovery.diagnostics import summarize
from corpus.qualification.policy import IssuePolicy


def main():
    policy = IssuePolicy()
    output = ROOT / "artifacts/discovery"
    output.mkdir(parents=True, exist_ok=True)
    reader = GitHubReader(os.environ["GITHUB_TOKEN"], FileSystemCAS(ROOT / ".bench/cas"), policy)
    seed = 13263128708966484217
    intake = AutomaticIntake(reader, policy, seed)
    rows = []
    try:
        for item in intake.candidates():
            if item["qualified"] or item["agent_ready"]:
                raise ValueError("Metadata intake must not certify a task")
            rows.append({key: item[key] for key in ("repository", "pull_number", "pre_fix_commit", "reference_commit", "status")})
            if len(rows) == 2:
                break
        if not rows:
            raise ValueError("NO_METADATA_ELIGIBLE_CANDIDATE_IN_AUTOMATIC_POOL")
    finally:
        result = summarize({"intake_rejections": intake.rejected, "api_requests": reader.requests},
            requested=None, qualified=0, stop_reason="METADATA_GATE_FINISHED", counts=intake.counts, searches=intake.searches)
        result.update(seed=seed, policy=asdict(policy), automatic_repositories=True,
                      metadata_candidates=rows, paid_model_called=False, builds_executed=False)
        (output / "automatic-metadata.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"metadata_candidates": rows, "counts": intake.counts, "reasons": result["reason_counts"]}, indent=2))


if __name__ == "__main__":
    main()
