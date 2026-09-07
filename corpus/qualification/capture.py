"""Read exact Git snapshots through existing cache/worktree owners. Never execute source."""
from pathlib import Path
from benchmark_core.checkout import SharedGitCache
from benchmark_core.worktree import WorktreeManager
from benchmark_core.identity import CommitPin, Sha256Digest
from .files import capture_files, code_view, is_code, is_test, safe_path, scale
from .policy import REPOSITORY


def acquire_task(candidate, root, policy):
    name = candidate["repository"]
    if not REPOSITORY.fullmatch(name):
        raise ValueError("INVALID_REPOSITORY")
    cache = SharedGitCache(Path(root) / ".bench/git-cache")
    manager = WorktreeManager(Path(root) / ".bench/worktrees")
    snapshots = []
    for key in ("pre_fix_commit", "reference_commit"):
        snapshot = cache.ensure("https://github.com/" + name + ".git", str(CommitPin(candidate[key])))
        with manager.disposable(snapshot) as worktree:
            files = capture_files(worktree.path, policy)
            manager.verify_pristine(worktree, expected_source_tree_digest=snapshot.source_tree_digest)
        snapshots.append((snapshot, files))
    (base, before), (fixed, after) = snapshots
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    code = sorted(path for path in changed if is_code(path))
    tests = sorted(path for path in changed if is_test(path) and Path(path).suffix == ".py")
    if not code or not tests:
        raise ValueError("NO_CODE_AND_TEST_CHANGE")
    if any(path not in before or path not in after for path in code):
        raise ValueError("SOURCE_CREATION_DELETION_UNSUPPORTED")
    if any(path not in after or Path(path).name == "conftest.py" for path in tests):
        raise ValueError("TEST_HARNESS_CHANGE_UNSUPPORTED")
    # Documentation/news can accompany a bug fix; build/config/fixture changes cannot.
    harmless = {path for path in changed if Path(path).suffix in {".md", ".rst", ".txt"}
                or "news" in Path(path).parts or "changelog" in Path(path).parts}
    if changed - set(code) - set(tests) - harmless:
        raise ValueError("NON_PYTHON_OR_ENVIRONMENT_CHANGE")
    for path in changed:
        safe_path(path)
    projection = code_view(before, policy.max_code_bytes)
    if any(before[path]["executable"] != after[path]["executable"] for path in code):
        raise ValueError("SOURCE_MODE_CHANGE_UNSUPPORTED")
    return {"candidate": candidate, "base_files": before, "base_source_digest": str(base.source_tree_digest),
            "fix_source_digest": str(fixed.source_tree_digest), "projection": projection,
            "fix_code": {path: after[path] for path in code}, "test_overlay": {path: after[path] for path in tests},
            "classification": scale(before), "identity": str(Sha256Digest.of(candidate))}
