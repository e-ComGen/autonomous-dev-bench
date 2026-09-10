from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.phase3d_adcp_compatibility_preflight import (
    TASK_REPOSITORY,
    TASK_REPOSITORY_COMMIT,
    TASKS,
    _ALLOWED_TASK_FILES,
    _FORBIDDEN_TASK_NAMES,
    changed_text,
    prepare_worktree,
    read_public_task_file,
)
from suites.coding.phase3d_scope import MAX_SCOPE_BYTES


def test_zero_paid_preflight_is_locked_to_exact_ten_public_tasks():
    assert TASK_REPOSITORY == "SWE-bench/swe-bench-tasks"
    assert TASK_REPOSITORY_COMMIT == "3d07b464b7b311a0cbfb5ed5b2d8a3b96f84a33d"
    assert len(TASKS) == 10
    assert TASKS["astropy__astropy-12907"] == (
        "astropy/astropy",
        "d16bfe05a744909de4b27f5875fe0d4ed41ce607",
    )
    assert TASKS["sympy__sympy-20590"] == (
        "sympy/sympy",
        "cffd4e0f86fefd4802349a9f9b19ed70934ea354",
    )


def test_zero_paid_preflight_task_input_firewall_is_explicit():
    assert _ALLOWED_TASK_FILES == frozenset({"task.yaml", "problem_statement.md"})
    assert {"gold.patch", "test.patch", "tests.json", "FAIL_TO_PASS", "PASS_TO_PASS"} <= _FORBIDDEN_TASK_NAMES
    for forbidden in _FORBIDDEN_TASK_NAMES:
        with pytest.raises(ValueError, match="non-public-evaluation input"):
            read_public_task_file(Path("unused"), "unused-task", forbidden)


def test_disposable_mutation_never_grows_an_exact_limit_projection():
    original = "value = 1\n"
    changed = changed_text(original, MAX_SCOPE_BYTES)
    assert changed != original
    assert len(changed.encode("utf-8")) <= len(original.encode("utf-8"))


def test_disposable_mutation_can_grow_only_when_budget_has_room():
    original = "value = 1"
    changed = changed_text(original, len(original.encode("utf-8")))
    assert changed == original + "\n"
    assert len(changed.encode("utf-8")) <= MAX_SCOPE_BYTES


def test_exact_limit_non_newline_mutation_is_same_size():
    original = "value = 1"
    changed = changed_text(original, MAX_SCOPE_BYTES)
    assert changed != original
    assert len(changed.encode("utf-8")) == len(original.encode("utf-8"))


def test_disposable_worktree_pins_autocrlf_before_checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    def run(path: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    run(source, "init", "-b", "main")
    run(source, "config", "user.name", "Test")
    run(source, "config", "user.email", "test@example.invalid")
    run(source, "config", "core.autocrlf", "false")
    (source / "source.py").write_bytes(b"value = 1\n")
    run(source, "add", "source.py")
    run(source, "commit", "-m", "baseline")
    commit = run(source, "rev-parse", "HEAD")

    bare = tmp_path / "source.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)],
        capture_output=True,
        text=True,
        check=True,
    )
    run(bare, "config", "core.autocrlf", "true")

    worktree = tmp_path / "worktree"
    prepare_worktree(bare, worktree, "autocrlf-regression", commit)

    assert run(bare, "config", "--get", "core.autocrlf") == "false"
    assert run(worktree, "-c", "core.autocrlf=false", "status", "--porcelain", "--untracked-files=all") == ""
