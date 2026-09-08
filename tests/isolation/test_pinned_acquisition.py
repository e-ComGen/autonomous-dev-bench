"""Real Git, warm-offline reuse, exact identity, early admission and bounded process count."""
from dataclasses import replace
import hashlib
import subprocess
import pytest
from benchmark_core.checkout import SharedGitCache, source_tree_digest, CheckoutError
from benchmark_core.git_objects import BlobReader, tree_entries
from benchmark_core.worktree import WorktreeManager
from corpus.qualification.inventory import validate_inventory
from corpus.qualification.policy import IssuePolicy


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.strip().decode()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    git(root, "init", "-b", "development")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "source.py").write_bytes(b"value = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    first = git(root, "rev-parse", "HEAD")
    (root / "source.py").write_bytes("value = 'ёж'\n".encode())
    git(root, "commit", "-qam", "fix")
    return root, first, git(root, "rev-parse", "HEAD")


def test_exact_old_pin_does_not_fetch_tip_or_history(source, tmp_path):
    root, old, tip = source
    snapshot = SharedGitCache(tmp_path / "cache").ensure(root.as_uri(), old)
    assert (snapshot.bare_repository / "shallow").is_file()
    assert git(snapshot.bare_repository, "rev-list", "--all", "--count") == "1"
    missing = subprocess.run(["git", "--git-dir", str(snapshot.bare_repository), "cat-file", "-e", tip], capture_output=True)
    assert missing.returncode != 0
    with WorktreeManager(tmp_path / "runs").disposable(snapshot) as tree:
        assert (tree.path / "source.py").read_bytes() == b"value = 1\n"
        assert source_tree_digest(tree.path) == snapshot.source_tree_digest


def test_warm_exact_pin_is_usable_after_remote_disappears(source, tmp_path):
    root, old, _ = source
    repository = root.as_uri()
    cache = SharedGitCache(tmp_path / "cache")
    first = cache.ensure(repository, old)
    root.rename(tmp_path / "unavailable-remote")
    second = cache.ensure(repository, old)
    assert first == second


def test_legacy_mirror_cache_is_reused_without_migration(source, tmp_path):
    root, old, tip = source
    cache = SharedGitCache(tmp_path / "cache")
    bare = cache._repository_path(str(root))
    bare.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "--mirror", str(root), str(bare)], check=True, capture_output=True)
    expected = cache.ensure(str(root), old)
    root.rename(tmp_path / "gone")
    assert cache.ensure(str(root), old) == expected
    assert cache.ensure(str(root), tip).commit == tip


def test_oversize_inventory_stops_before_payload_hash(source, tmp_path, monkeypatch):
    root, _, tip = source
    import benchmark_core.checkout as checkout
    monkeypatch.setattr(checkout, "digest_tree", lambda *args: pytest.fail("must reject before hashing"))
    policy = replace(IssuePolicy(), max_file_bytes=1024, max_repository_bytes=1024)
    (root / "oversize.bin").write_bytes(b"x" * 2048)
    git(root, "add", ".")
    git(root, "commit", "-qm", "oversize")
    with pytest.raises(ValueError, match="SOURCE_SIZE_LIMIT"):
        SharedGitCache(tmp_path / "cache").ensure(root.as_uri(), git(root, "rev-parse", "HEAD"),
            tree_validator=lambda entries: validate_inventory(entries, policy))


def test_batch_reader_checks_size_and_identity(source, tmp_path):
    root, old, _ = source
    snapshot = SharedGitCache(tmp_path / "cache").ensure(root.as_uri(), old)
    entry = tree_entries(snapshot.bare_repository, old)[0]
    with BlobReader(snapshot.bare_repository) as reader:
        assert reader.read(entry.oid, entry.size) == b"value = 1\n"
    with BlobReader(snapshot.bare_repository) as reader, pytest.raises(CheckoutError):
        reader.read(entry.oid, entry.size + 1)


def test_many_files_do_not_create_many_cat_file_processes(source, tmp_path, monkeypatch):
    root, _, _ = source
    for number in range(180):
        (root / f"item{number:04}.py").write_bytes(f"value={number}\n".encode())
    git(root, "add", ".")
    git(root, "commit", "-qm", "many")
    original = subprocess.Popen
    calls = []
    def traced(args, *rest, **kwargs):
        calls.append(list(args))
        return original(args, *rest, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", traced)
    snapshot = SharedGitCache(tmp_path / "cache").ensure(root.as_uri(), git(root, "rev-parse", "HEAD"))
    with WorktreeManager(tmp_path / "runs").disposable(snapshot) as tree:
        assert source_tree_digest(tree.path) == snapshot.source_tree_digest
    readers = [args for args in calls if "cat-file" in args and "--batch" in args]
    assert len(readers) == 2
    assert not [args for args in calls if "cat-file" in args and "blob" in args]
    assert len(calls) < 30
