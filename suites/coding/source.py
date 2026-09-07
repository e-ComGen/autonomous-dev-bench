"""Acquire through existing owners, then build an explicit common source projection."""
from pathlib import Path
import ast
import hashlib
import shutil

from benchmark_core.worktree import WorktreeManager
from cli.oneclick.project_worker import acquire


def omit_function(source: str, symbol: str) -> str:
    matches = [node for node in ast.parse(source).body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one top-level function: {symbol}")
    node = matches[0]
    body = node.body
    if (len(body) > 1 and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
        body = body[1:]
    lines = source.splitlines(keepends=True)
    replacement = ' ' * body[0].col_offset + 'raise NotImplementedError("Benchmark reconstruction task")\n'
    return ''.join(lines[:body[0].lineno - 1]) + replacement + ''.join(lines[node.end_lineno:])


def snapshot_files(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("A candidate must not contain symlinks")
        if path.is_file():
            if path.stat().st_size > 1000000:
                raise ValueError("A candidate file exceeded the source bound")
            result[relative.as_posix()] = path.read_text(encoding="utf-8")
    if sum(len(value.encode()) for value in result.values()) > 1000000:
        raise ValueError("The current ADCP source projection is limited to 1,000,000 bytes")
    return result


def write_files(directory: Path, files: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise ValueError("Invalid projected source path")
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def project_source(root, entry, recipe, destination, network=False):
    pinned = acquire(root, entry, root / ".bench/seeds", network)
    manager = WorktreeManager(destination.parent / "worktrees")
    with manager.disposable(pinned) as worktree:
        manager.verify_pristine(worktree, expected_source_tree_digest=entry.source_digest)
        package = worktree.path / recipe.package_root
        if not package.is_dir():
            # Requests changed from a flat package to src layout; pin determines which exists.
            package = worktree.path / recipe.module.split('.')[0]
        if not package.is_dir():
            raise ValueError("Pinned package directory is missing")
        files = {}
        for path in sorted(package.rglob("*")):
            if path.is_symlink():
                raise ValueError("Source projection refuses linked package files")
            if path.is_file() and path.suffix == ".py":
                files[(Path(recipe.module.split('.')[0]) / path.relative_to(package)).as_posix()] = path.read_text(encoding="utf-8")
        version_file = recipe.module.split('.')[0] + "/_version.py"
        if recipe.module.startswith("pluggy.") and version_file not in files:
            files[version_file] = '__version__ = version = "0+benchmark"\n__version_tuple__ = version_tuple = (0,)\n'
        write_files(destination, files)
    return files
