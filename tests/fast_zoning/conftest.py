from __future__ import annotations

import subprocess
import hashlib
import json
import sys

import pytest


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout.decode().strip()


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Offline fixture")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "logic.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "old.txt").write_text("rename evidence\n", encoding="utf-8")
    (repo / "delete.txt").write_text("delete evidence\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "clean fixture")
    clean_head = git(repo, "rev-parse", "HEAD")
    clean_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "logic.py").write_text("value = 0\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "buggy fixture")
    return {"repo": str(repo), "clean_head": clean_head, "clean_tree": clean_tree,
            "buggy_head": git(repo, "rev-parse", "HEAD"),
            "buggy_tree": git(repo, "rev-parse", "HEAD^{tree}")}


@pytest.fixture
def task_manifest(source_repo, tmp_path):
    from benchmark_core.fast_zoning.manifest import CATEGORIES, DEFAULT_EXECUTION, plan_digest
    task = "Restore the expected value without changing other behavior."
    task_hash = hashlib.sha256(task.encode()).hexdigest()
    evaluator = tmp_path / "evaluate.py"
    evaluator.write_text("import json\nprint(json.dumps({'status':'PASS'}))\n", encoding="utf-8")
    evaluator_hash = hashlib.sha256(evaluator.read_bytes()).hexdigest()
    plan = {"phase": "PREDECLARED", "frozen": True,
            "benchmark_head": source_repo["buggy_head"], "benchmark_tree": source_repo["buggy_tree"],
            "task_hash": task_hash, "evaluators": [
                {"id": category, "category": category, "required": True,
                 "identity": "offline fixture v1", "command": [sys.executable, "{artifact0}"],
                 "timeout_seconds": 10,
                 "artifacts": [{"path": str(evaluator), "sha256": evaluator_hash}]}
                for category in CATEGORIES]}
    context = {}
    for arm in ("A", "B"):
        packet = tmp_path / f"{arm}.md"
        packet.write_text(task + "\n", encoding="utf-8")
        context[arm] = {"packet_path": str(packet), "packet_hash": hashlib.sha256(packet.read_bytes()).hexdigest(),
                        "packet_bytes": packet.stat().st_size, "source_item_count": 0, "source_bytes": 0}
    zoning = tmp_path / "zones.json"
    zoning.write_text('{"zones": []}', encoding="utf-8")
    context["B"]["zoning"] = {"zone_id": "fixture-zone", "artifact_paths": ["logic.py"],
                                 "snapshot_id": "fixture-snapshot", "analysis_digest": "a" * 64}
    data = {"schema_version": 1, "task_id": "TEST-01", **source_repo,
            "task_text": task, "task_hash": task_hash, "evaluation_plan": plan,
            "evaluation_plan_digest": plan_digest(plan), "run_order_seed": "offline-fixture-seed",
            "contexts": context, "execution": dict(DEFAULT_EXECUTION), "model_executed": False}
    path = tmp_path / "task.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
