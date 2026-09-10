from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from suites.coding.phase3d_scope import MAX_SCOPE_BYTES, SCOPE_POLICY, select_write_scope


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "benchmark")
    git(repo, "config", "user.name", "scope-test")
    git(repo, "config", "user.email", "scope@example.invalid")
    paths = {
        "package/separable.py": "def separability_matrix(model):\n    return model.matrix\n",
        "package/unrelated.py": "def unrelated():\n    return 1\n",
        "tests/test_separable.py": "def test_separability_matrix():\n    assert False\n",
    }
    for relative, content in paths.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "baseline")
    return repo


def test_static_scope_is_deterministic_public_only_and_excludes_tests(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    instruction = "Fix `separability_matrix` for nested CompoundModels."
    one = select_write_scope(str(repo), instruction)
    two = select_write_scope(str(repo), instruction)

    assert one == two
    assert one.policy == SCOPE_POLICY
    assert "package/separable.py" in one.paths
    assert all(not path.startswith("tests/") for path in one.paths)
    assert one.visible_bytes <= MAX_SCOPE_BYTES
    assert one.digest.startswith("sha256:")


def test_static_scope_identity_changes_with_public_instruction(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    first = select_write_scope(str(repo), "Fix separability_matrix nested behavior")
    second = select_write_scope(str(repo), "Fix unrelated return behavior")
    assert first.digest != second.digest


def test_static_scope_fails_closed_when_no_source_symbol_matches(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    with pytest.raises(ValueError, match="no bounded source candidate"):
        select_write_scope(str(repo), "zzzzcompletelyunknownsymbolzzzz")


def test_static_scope_never_grants_write_authority_to_100755_python(tmp_path: Path):
    repo = fixture_repo(tmp_path)
    executable = repo / "package" / "executable.py"
    executable.write_text("def executable_only_symbol():\n    return 1\n", encoding="utf-8")
    git(repo, "add", "package/executable.py")
    git(repo, "update-index", "--chmod=+x", "package/executable.py")
    git(repo, "commit", "-m", "add executable python")
    assert git(repo, "ls-tree", "HEAD", "package/executable.py").startswith("100755 blob ")

    with pytest.raises(ValueError, match="no bounded source candidate"):
        select_write_scope(str(repo), "Fix executable_only_symbol behavior")
