"""Exact pins through the existing cache and worktree owners. Never execute project code."""
from pathlib import Path
import subprocess
from benchmark_core.checkout import SharedGitCache
from benchmark_core.worktree import WorktreeManager
from benchmark_core.identity import CommitPin, Sha256Digest
from .files import capture_files, code_view, scale
from .changes import partition
from .policy import REPOSITORY
from .inventory import validate_inventory


def canonical_modes(directory):
    completed = subprocess.run(["git", "-C", str(directory), "ls-files", "--stage", "-z"],
                               capture_output=True, check=True, timeout=30)
    result = {}
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        metadata, path = item.split(b"\t", 1)
        mode, _, stage = metadata.split()
        if stage != b"0" or mode not in (b"100644", b"100755"):
            raise ValueError("UNSUPPORTED_GIT_FILE_MODE")
        result[path.decode("utf-8")] = mode == b"100755"
    return result


def acquire_task(candidate, root, policy, progress=None):
    name = candidate["repository"]
    if not REPOSITORY.fullmatch(name):
        raise ValueError("INVALID_REPOSITORY")
    notify = progress or (lambda stage, **details: None)
    cache = SharedGitCache(Path(root) / ".bench/git-cache")
    manager = WorktreeManager(Path(root) / ".bench/worktrees")
    snapshots = []
    for key in ("pre_fix_commit", "reference_commit"):
        def stage(value, **details):
            notify(key + "." + value, **details)
        snapshot = cache.ensure("https://github.com/" + name + ".git", str(CommitPin(candidate[key])),
            tree_validator=lambda entries: validate_inventory(entries, policy, check_code_size=key == "pre_fix_commit"),
            progress=stage)
        stage("materialize")
        with manager.disposable(snapshot) as worktree:
            stage("capture")
            files = capture_files(worktree.path, policy)
            modes = canonical_modes(worktree.path)
            if set(files) != set(modes):
                raise ValueError("CAPTURE_DIFFERS_FROM_PINNED_GIT_PATHS")
            for relative, record in files.items():
                record["executable"] = modes[relative]
            stage("verify_pristine")
            manager.verify_pristine(worktree, expected_source_tree_digest=snapshot.source_tree_digest)
        snapshots.append((snapshot, files))
    notify("partition_and_source_view")
    (base, before), (fixed, after) = snapshots
    code, tests = partition(before, after)
    projection = code_view(before, policy.max_code_bytes)
    if any(before[path]["executable"] != after[path]["executable"] for path in code):
        raise ValueError("SOURCE_MODE_CHANGE_UNSUPPORTED")
    return {"candidate": candidate, "base_files": before, "base_source_digest": str(base.source_tree_digest),
            "fix_source_digest": str(fixed.source_tree_digest), "projection": projection,
            "fix_code": {path: after[path] for path in code}, "test_overlay": {path: after[path] for path in tests},
            "classification": scale(before), "identity": str(Sha256Digest.of(candidate))}
