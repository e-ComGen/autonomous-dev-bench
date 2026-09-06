import subprocess
import sys

import pytest

from benchmark_core.checkout import SharedGitCache, SourceTreeDigestMismatch, source_tree_digest
from benchmark_core.environment import BaselineHealthRunner, EnvironmentFingerprint
from benchmark_core.execution import CommandSpec
from benchmark_core.isolation import IsolationCapabilities, IsolationPolicy, IsolationUnavailable, validate_isolation
from benchmark_core.result import RunStatus
from benchmark_core.worktree import WorktreeManager


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout.strip()


def test_local_git_worktrees_are_detached_and_isolated(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); git(repo, "init")
    git(repo, "config", "user.email", "benchmark@example.invalid"); git(repo, "config", "user.name", "Benchmark")
    (repo / "value.txt").write_text("original", encoding="utf-8")
    git(repo, "add", "value.txt"); git(repo, "commit", "-m", "initial")
    commit = git(repo, "rev-parse", "HEAD")
    cache = SharedGitCache(tmp_path / "git-cache")
    snapshot = cache.ensure(str(repo), commit)
    assert cache.ensure(str(repo), commit,
                        expected_source_tree_digest=snapshot.source_tree_digest).source_tree_digest == snapshot.source_tree_digest
    with pytest.raises(SourceTreeDigestMismatch):
        cache.ensure(str(repo), commit, expected_source_tree_digest="sha256:" + "0" * 64)
    manager = WorktreeManager(tmp_path / "runs")
    with manager.disposable(snapshot) as first, manager.disposable(snapshot) as second:
        assert git(first.path, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
        (first.path / "value.txt").write_text("changed", encoding="utf-8")
        assert (second.path / "value.txt").read_text(encoding="utf-8") == "original"
        assert source_tree_digest(second.path) == snapshot.source_tree_digest
        assert source_tree_digest(first.path) != source_tree_digest(second.path)
        first_path = first.path
    assert not first_path.exists()


def test_authoritative_isolation_fails_closed():
    with pytest.raises(IsolationUnavailable):
        validate_isolation(IsolationPolicy(), IsolationCapabilities())


def test_baseline_failure_is_not_sut_failure(tmp_path):
    env = EnvironmentFingerprint.current(project_source_digest="sha256:" + "1" * 64,
        repository_commit="a" * 40, dependency_lock_digest="sha256:" + "2" * 64)
    health = BaselineHealthRunner().run("sha256:" + "3" * 64,
        env, CommandSpec((sys.executable, "-c", "raise SystemExit(2)"), cwd=str(tmp_path)))
    assert health.status is RunStatus.BASELINE_BROKEN
    assert health.status is not RunStatus.FAIL
