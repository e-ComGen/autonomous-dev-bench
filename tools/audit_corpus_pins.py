"""Verify file pins inside already tree-verified public Git commits; never update them."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from benchmark_core.checkout import SharedGitCache
from benchmark_core.manifest import load_json


def audit() -> None:
    result = []
    for path in sorted((ROOT / "corpus/projects").glob("*.json")):
        data = load_json(path)
        source = data["source"]
        snapshot = SharedGitCache(ROOT / ".bench/git-cache").ensure(
            source["repository"], source["commit_sha"],
            expected_source_tree_digest=source["source_tree_digest"])
        pairs = [(data["legal"]["license_file"], data["legal"]["license_file_digest"])]
        pairs.extend(zip(data["bootstrap"]["dependency_spec_paths"],
                         data["bootstrap"]["dependency_spec_digests"], strict=True))
        for relative, expected in pairs:
            payload = subprocess.run(["git", "--git-dir", str(snapshot.bare_repository), "show",
                                      snapshot.commit + ":" + relative], check=True,
                                     capture_output=True, timeout=30).stdout
            record = {"project": data["project_id"], "commit": snapshot.commit,
                      "source_tree_verified": True, "file": relative, "expected": expected,
                      "raw_sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}
            result.append(record)
            print(json.dumps(record, sort_keys=True))
    target = ROOT / "artifacts/pin-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if any(item["expected"] != item["raw_sha256"] for item in result):
        raise ValueError("Pinned file bytes differ; no manifest was changed")


if __name__ == "__main__":
    audit()
