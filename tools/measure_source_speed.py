"""Paired acquisition microbenchmark on identical exact Git bytes, not a coding score."""
from pathlib import Path
import importlib
import json
import subprocess
import sys
import tempfile
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
BASE = "747dfd15a909ff711cb2cf77c94ac46e81a55705"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def measure(cache_type, manager_type, repository, commit, destination):
    original = subprocess.Popen
    calls = []
    def traced(args, *rest, **kwargs):
        calls.append(list(map(str, args)))
        return original(args, *rest, **kwargs)
    subprocess.Popen = traced
    start = time.monotonic()
    try:
        cache = cache_type(destination / "cache")
        snapshot = cache.ensure(repository.as_uri(), commit)
        with manager_type(destination / "worktrees").disposable(snapshot) as worktree:
            manager_type(destination / "verify").verify_pristine(worktree, expected_source_tree_digest=snapshot.source_tree_digest)
        cold = {"wall_seconds": time.monotonic() - start, "git_processes": len(calls),
                "blob_processes": sum("cat-file" in argv and ("blob" in argv or "--batch" in argv) for argv in calls),
                "source_digest": snapshot.source_tree_digest}
        calls.clear()
        start = time.monotonic()
        warm = cache.ensure(repository.as_uri(), commit)
        assert warm.source_tree_digest == snapshot.source_tree_digest
        cold["warm"] = {"wall_seconds": time.monotonic() - start, "git_processes": len(calls),
                        "fetches": sum("fetch" in argv for argv in calls)}
        return cold
    finally:
        subprocess.Popen = original


def main():
    from benchmark_core.checkout import SharedGitCache
    from benchmark_core.worktree import WorktreeManager
    with tempfile.TemporaryDirectory(prefix="source-perf-") as temporary:
        root = Path(temporary)
        legacy = root / "legacy_core"
        legacy.mkdir()
        (legacy / "__init__.py").write_text("")
        for name in ("checkout", "worktree"):
            source = git(ROOT, "show", BASE + ":packages/benchmark_core/benchmark_core/" + name + ".py")
            (legacy / (name + ".py")).write_bytes(source)
        sys.path.insert(0, str(root))
        old_cache = importlib.import_module("legacy_core.checkout").SharedGitCache
        old_manager = importlib.import_module("legacy_core.worktree").WorktreeManager
        repository = root / "remote"
        repository.mkdir()
        git(repository, "init", "-b", "development")
        git(repository, "config", "user.name", "Performance test")
        git(repository, "config", "user.email", "test@example.invalid")
        for number in range(512):
            (repository / f"module_{number:04}.py").write_bytes((f"value = {number}\n" + "# exact bytes\n" * 60).encode())
        git(repository, "add", ".")
        git(repository, "commit", "-qm", "benchmark pin")
        commit = git(repository, "rev-parse", "HEAD").strip().decode()
        for number in range(3):
            (repository / "unrelated.bin").write_bytes(bytes([number]) * 1000000)
            git(repository, "add", ".")
            git(repository, "commit", "-qm", "unrelated future history")
        before = measure(old_cache, old_manager, repository, commit, root / "old")
        after = measure(SharedGitCache, WorktreeManager, repository, commit, root / "new")
        assert before["source_digest"] == after["source_digest"]
        assert after["blob_processes"] == 2 and after["git_processes"] < before["git_processes"] / 10
        assert after["warm"]["fetches"] == 0
        result = {"platform": sys.platform, "python": sys.version, "files": 512,
                  "baseline": BASE, "candidate": git(ROOT, "rev-parse", "HEAD").strip().decode(),
                  "before": before, "after": after, "byte_identical": True,
                  "cold_speed_ratio": before["wall_seconds"] / after["wall_seconds"],
                  "live_model_called": False, "scope": "LOCAL_GIT_ACQUISITION_ONLY"}
        output = ROOT / "artifacts/source-speed.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
