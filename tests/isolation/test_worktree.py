import subprocess
import sys

import pytest

from benchmark_core.checkout import CheckoutError, SharedGitCache, SourceTreeDigestMismatch, source_tree_digest
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


def test_materialization_restores_canonical_blob_bytes_after_eol_filters(tmp_path):
    repo = tmp_path / "eol-repo"; repo.mkdir(); git(repo, "init")
    git(repo, "config", "user.email", "benchmark@example.invalid"); git(repo, "config", "user.name", "Benchmark")
    (repo / ".gitattributes").write_text("*.txt text eol=crlf\n", encoding="utf-8")
    (repo / "value.txt").write_bytes(b"line-one\nline-two\n")
    git(repo, "add", ".gitattributes", "value.txt"); git(repo, "commit", "-m", "eol")
    cache = SharedGitCache(tmp_path / "git-cache")
    snapshot = cache.ensure(str(repo), git(repo, "rev-parse", "HEAD"))
    manager = WorktreeManager(tmp_path / "runs")
    with manager.disposable(snapshot) as worktree:
        assert (worktree.path / "value.txt").read_bytes() == b"line-one\nline-two\n"
        manager.verify_pristine(worktree, expected_source_tree_digest=snapshot.source_tree_digest)


def test_materialization_fails_closed_when_pinned_symlink_is_unavailable(tmp_path, monkeypatch):
    repo = tmp_path / "symlink-repo"; repo.mkdir(); git(repo, "init")
    git(repo, "config", "user.email", "benchmark@example.invalid"); git(repo, "config", "user.name", "Benchmark")
    target = repo / "nested" / "target-dir"; target.mkdir(parents=True); (target / "value.txt").write_text("destination", encoding="utf-8")
    payload = repo / "link-payload"; payload.write_text("nested/target-dir", encoding="utf-8")
    blob = git(repo, "hash-object", "-w", "link-payload"); payload.unlink()
    git(repo, "add", "nested/target-dir/value.txt")
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},link")
    git(repo, "commit", "-m", "symlink")
    snapshot = SharedGitCache(tmp_path / "git-cache").ensure(str(repo), git(repo, "rev-parse", "HEAD"))
    with WorktreeManager(tmp_path / "valid-runs").disposable(snapshot) as worktree:
        assert (worktree.path / "link").is_symlink() and (worktree.path / "link").is_dir()
        assert source_tree_digest(worktree.path) == snapshot.source_tree_digest
    monkeypatch.setattr(type(tmp_path), "symlink_to", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(CheckoutError, match="cannot materialize pinned symlink"):
        WorktreeManager(tmp_path / "runs").create(snapshot)


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
