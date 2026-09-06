"""Disposable detached worktrees with robust cleanup and copy fallback."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterator

from .checkout import CheckoutError, RepositorySnapshot, source_tree_digest


@dataclass(frozen=True)
class Worktree:
    path: Path
    snapshot: RepositorySnapshot
    linked: bool


class WorktreeManager:
    def __init__(self, runs_root: str | os.PathLike[str]) -> None:
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], check=check, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, shell=False)

    def create(self, snapshot: RepositorySnapshot, destination: str | os.PathLike[str] | None = None,
               *, allow_copy_fallback: bool = True) -> Worktree:
        path = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="worktree-", dir=self.runs_root))
        if path.exists() and any(path.iterdir()):
            raise FileExistsError(f"worktree destination is not empty: {path}")
        if path.exists():
            path.rmdir()
        try:
            self._run_git("-c", "core.autocrlf=false", "-c", "core.symlinks=true", "--git-dir", str(snapshot.bare_repository), "worktree", "add",
                          "--detach", "--force", str(path), snapshot.commit)
            return Worktree(path, snapshot, True)
        except (OSError, subprocess.CalledProcessError) as exc:
            if not allow_copy_fallback:
                raise CheckoutError(f"could not create linked worktree: {exc}") from exc
            # A local clone shares objects when possible, but remains disposable.
            try:
                self._run_git("clone", "--no-checkout", "--shared", str(snapshot.bare_repository), str(path))
                self._run_git("-C", str(path), "config", "core.autocrlf", "false")
                self._run_git("-C", str(path), "config", "core.symlinks", "true")
                self._run_git("-C", str(path), "checkout", "--detach", snapshot.commit)
            except (OSError, subprocess.CalledProcessError) as fallback_exc:
                shutil.rmtree(path, ignore_errors=True)
                raise CheckoutError(f"worktree and copy fallback failed: {fallback_exc}") from fallback_exc
            return Worktree(path, snapshot, False)

    def verify_pristine(self, worktree: Worktree, *, expected_source_tree_digest: str | None = None) -> None:
        head = self._run_git("-C", str(worktree.path), "rev-parse", "HEAD").stdout.strip().lower()
        if head != worktree.snapshot.commit.lower():
            raise CheckoutError(f"worktree HEAD mismatch: expected {worktree.snapshot.commit}, got {head}")
        status = self._run_git("-C", str(worktree.path), "status", "--porcelain=v1", "--untracked-files=all").stdout
        if status:
            raise CheckoutError("new worktree is not pristine before overlays")
        if expected_source_tree_digest is not None:
            actual = source_tree_digest(worktree.path)
            if actual != expected_source_tree_digest:
                raise CheckoutError(
                    f"materialized worktree bytes differ from pinned source tree: expected {expected_source_tree_digest}, got {actual}"
                )

    def cleanup(self, worktree: Worktree | str | os.PathLike[str]) -> None:
        item = worktree if isinstance(worktree, Worktree) else None
        path = item.path if item else Path(worktree)
        if item and item.linked:
            self._run_git("--git-dir", str(item.snapshot.bare_repository), "worktree", "remove",
                          "--force", str(path), check=False)
            self._run_git("--git-dir", str(item.snapshot.bare_repository), "worktree", "prune", check=False)
        shutil.rmtree(path, ignore_errors=True)

    def recover(self, bare_repository: str | os.PathLike[str]) -> None:
        self._run_git("--git-dir", str(bare_repository), "worktree", "prune", check=False)

    @contextmanager
    def disposable(self, snapshot: RepositorySnapshot, destination: str | os.PathLike[str] | None = None,
                   *, allow_copy_fallback: bool = True) -> Iterator[Worktree]:
        worktree = self.create(snapshot, destination, allow_copy_fallback=allow_copy_fallback)
        try:
            yield worktree
        finally:
            self.cleanup(worktree)

    materialize = disposable
