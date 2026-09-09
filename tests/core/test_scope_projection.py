from __future__ import annotations

from pathlib import Path
import subprocess

from suites.coding.scope_projection import SCOPE_POLICY, project_task_scope


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Scope Test")
    git(root, "config", "user.email", "scope@example.invalid")
    files = {
        "pkg/cache_backend.py": "class CacheBackend:\n    def invalidate(self, key):\n        return False\n",
        "pkg/parser.py": "def parse(value):\n    return value\n",
        "pkg/utils.py": "def helper(value):\n    return value\n",
        "tests/test_cache.py": "def test_cache():\n    pass\n",
        "docs/cache.md": "Cache behavior documentation.\n",
        "README.md": "Example project.\n",
    }
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\xff\x00binary")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    return root


def test_identifier_and_content_rank_the_relevant_source_first(tmp_path: Path) -> None:
    root = repository(tmp_path)
    result = project_task_scope(
        root,
        "`CacheBackend.invalidate` should invalidate the requested cache key.",
        max_write_paths=4,
        max_read_paths=2,
        max_read_bytes=4096,
    )
    assert result.policy == SCOPE_POLICY
    assert result.write_paths[0] == "pkg/cache_backend.py"
    assert result.read_paths[0] == "pkg/cache_backend.py"
    assert "blob.bin" not in result.write_paths
    assert result.read_bytes <= 4096


def test_projection_is_deterministic_for_exact_baseline_and_problem(tmp_path: Path) -> None:
    root = repository(tmp_path)
    problem = "Fix parser parse behavior for values while preserving existing behavior."
    first = project_task_scope(root, problem, max_write_paths=5, max_read_paths=3, max_read_bytes=4096)
    second = project_task_scope(root, problem, max_write_paths=5, max_read_paths=3, max_read_bytes=4096)
    assert first == second
    assert first.identity == second.identity
    assert first.baseline_commit == git(root, "rev-parse", "HEAD")


def test_unrelated_hidden_material_outside_baseline_cannot_change_scope(tmp_path: Path) -> None:
    root = repository(tmp_path)
    problem = "Fix CacheBackend invalidate behavior."
    before = project_task_scope(root, problem, max_write_paths=4, max_read_paths=2, max_read_bytes=4096)

    hidden = tmp_path / "gold.patch"
    hidden.write_text("pkg/parser.py should win hidden oracle ranking\n", encoding="utf-8")
    after = project_task_scope(root, problem, max_write_paths=4, max_read_paths=2, max_read_bytes=4096)
    assert before == after


def test_static_read_projection_can_be_smaller_than_write_authority(tmp_path: Path) -> None:
    root = repository(tmp_path)
    result = project_task_scope(
        root,
        "Fix CacheBackend invalidation and parser behavior.",
        max_write_paths=5,
        max_read_paths=1,
        max_read_bytes=4096,
    )
    assert len(result.write_paths) == 5
    assert len(result.read_paths) == 1
    assert set(result.read_paths) <= set(result.write_paths)


def test_read_budget_skips_oversized_file_without_changing_write_rank(tmp_path: Path) -> None:
    root = repository(tmp_path)
    large = root / "pkg" / "giant_cache.py"
    large.write_text("CacheBackend invalidate\n" + "x" * 5000, encoding="utf-8")
    git(root, "add", "pkg/giant_cache.py")
    git(root, "commit", "-m", "large source")

    result = project_task_scope(
        root,
        "Fix giant_cache CacheBackend invalidate.",
        max_write_paths=4,
        max_read_paths=2,
        max_read_bytes=512,
    )
    assert "pkg/giant_cache.py" in result.write_paths
    assert "pkg/giant_cache.py" not in result.read_paths
    assert result.read_bytes <= 512
