"""Real local source/worktree/tests negative control, explicitly not a model benchmark."""
from pathlib import Path
import os
import shutil
import sys

from benchmark_core.checkout import SharedGitCache, source_tree_digest
from benchmark_core.execution import CommandSpec, ProcessRunner
from benchmark_core.worktree import WorktreeManager
from .test_results import junit_counts, log_result, test_succeeded


def _command(runner: ProcessRunner, argv: tuple[str, ...], cwd: Path) -> str:
    result = runner.run(CommandSpec(argv, 30, str(cwd)))
    if not result.succeeded:
        raise RuntimeError("Selftest Git setup failed")
    return result.stdout.strip()


def _pytest(runner, report, workspace: Path, stage: str, timeout: int):
    junit = report.directory / (stage + ".xml")
    command = CommandSpec((sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "--color=no", "--tb=short", "--junitxml=" + str(junit), "tests"),
                          timeout, str(workspace), {"PYTHONPATH": str(workspace / "src"),
                                                   "PYTHONDONTWRITEBYTECODE": "1"})
    result = runner.run(command)
    counts = junit_counts(junit)
    return result, counts, log_result(report, stage, result)


def run_selftest(root: Path, report, timeout: int = 60) -> dict:
    source = root / "reference_projects/benchmark_selftest_project"
    if not source.is_dir():
        raise ValueError("BUNDLED_SELFTEST_PROJECT_MISSING")
    repository = report.directory / "selftest-source"
    shutil.copytree(source, repository, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    runner = ProcessRunner()
    try:
        _command(runner, ("git", "init", "-q"), repository)
        _command(runner, ("git", "config", "core.autocrlf", "false"), repository)
        _command(runner, ("git", "add", "."), repository)
        _command(runner, ("git", "-c", "user.name=Benchmark Selftest", "-c", "user.email=selftest@example.invalid",
                          "-c", "commit.gpgsign=false", "commit", "-qm", "Local fixture snapshot"), repository)
        commit = _command(runner, ("git", "rev-parse", "HEAD"), repository)
        digest = source_tree_digest(repository)
        snapshot = SharedGitCache(report.directory / "selftest-cache").ensure(
            str(repository), commit, expected_source_tree_digest=digest)
        manager = WorktreeManager(report.directory / "selftest-worktrees")
        with manager.disposable(snapshot) as worktree:
            manager.verify_pristine(worktree, expected_source_tree_digest=digest)
            before, before_counts, before_log = _pytest(runner, report, worktree.path, "control-before", timeout)
            target = worktree.path / "src/selftest_app/providers.py"
            original = target.read_bytes()
            if original.count(b"return value.upper()") != 1:
                raise ValueError("Bundled negative-control target changed")
            target.write_bytes(original.replace(b"return value.upper()", b"return value.lower()"))
            broken, broken_counts, broken_log = _pytest(runner, report, worktree.path, "control-broken", timeout)
            target.write_bytes(original)
            after, after_counts, after_log = _pytest(runner, report, worktree.path, "control-restored", timeout)
            manager.verify_pristine(worktree, expected_source_tree_digest=digest)
        detected = (broken.returncode == 1 and not broken.timed_out
                    and broken_counts["failures"] > 0 and broken_counts["errors"] == 0)
        passed = test_succeeded(before, before_counts) and detected and test_succeeded(after, after_counts)
        return {"status": "SELFTEST_OK" if passed else "SELFTEST_FAILED", "negative_control_detected": detected,
                "source_digest": digest, "coding_quality_measured": False,
                "stages": [{"name": name, "counts": counts, **log}
                           for name, counts, log in (("before", before_counts, before_log),
                                                     ("broken", broken_counts, broken_log),
                                                     ("restored", after_counts, after_log))]}
    finally:
        for name in ("selftest-source", "selftest-cache", "selftest-worktrees"):
            shutil.rmtree(report.directory / name, ignore_errors=True)
