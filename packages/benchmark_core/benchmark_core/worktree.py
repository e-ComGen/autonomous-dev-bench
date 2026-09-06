"""Disposable detached worktrees with robust cleanup and copy fallback."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import posixpath
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

    def _restore_canonical_git_bytes(self, path: Path, snapshot: RepositorySnapshot) -> None:
        """Undo checkout filters/EOL conversion so bytes equal the pinned Git blobs."""
        listing = subprocess.run(["git", "--git-dir", str(snapshot.bare_repository), "ls-tree", "-r", "-z", "--full-tree", snapshot.commit],
                                 check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout
        entries = [entry for entry in listing.split(b"\0") if entry]
        tracked_paths = {entry.split(b"\t", 1)[1].decode("utf-8", "surrogateescape") for entry in entries}
        for entry in entries:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            if kind != b"blob": raise CheckoutError("canonical worktree only supports Git blobs")
            relative = raw_path.decode("utf-8", "surrogateescape")
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise CheckoutError("Git tree path escapes worktree")
            target = path / relative_path
            payload = subprocess.run(["git", "--git-dir", str(snapshot.bare_repository), "cat-file", "blob", object_id.decode("ascii")],
                                     check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink(): target.unlink()
            if mode == b"120000":
                link_target = payload.decode("utf-8", "surrogateescape")
                resolved_target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link_target))
                target_is_directory = any(item.startswith(resolved_target.rstrip("/") + "/") for item in tracked_paths)
                try:
                    target.symlink_to(link_target.replace("/", os.sep), target_is_directory=target_is_directory)
                    expected_target = (target.parent / link_target).resolve(strict=False)
                    if expected_target.exists() and not target.exists():
                        target.unlink()
                        target.symlink_to(expected_target, target_is_directory=target_is_directory)
                except OSError as exc: raise CheckoutError(f"cannot materialize pinned symlink: {relative}") from exc
            else:
                target.write_bytes(payload)
                if mode == b"100755": target.chmod(target.stat().st_mode | 0o111)

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
            self._restore_canonical_git_bytes(path, snapshot)
            return Worktree(path, snapshot, True)
        except CheckoutError:
            self._run_git("--git-dir", str(snapshot.bare_repository), "worktree", "remove", "--force", str(path), check=False)
            shutil.rmtree(path, ignore_errors=True)
            raise
        except (OSError, subprocess.CalledProcessError) as exc:
            if not allow_copy_fallback:
                raise CheckoutError(f"could not create linked worktree: {exc}") from exc
            # A local clone shares objects when possible, but remains disposable.
            try:
                self._run_git("clone", "--no-checkout", "--shared", str(snapshot.bare_repository), str(path))
                self._run_git("-C", str(path), "config", "core.autocrlf", "false")
                self._run_git("-C", str(path), "config", "core.symlinks", "true")
                self._run_git("-C", str(path), "checkout", "--detach", snapshot.commit)
                self._restore_canonical_git_bytes(path, snapshot)
            except (OSError, subprocess.CalledProcessError, CheckoutError) as fallback_exc:
                shutil.rmtree(path, ignore_errors=True)
                raise CheckoutError(f"worktree and copy fallback failed: {fallback_exc}") from fallback_exc
            return Worktree(path, snapshot, False)

    def verify_pristine(self, worktree: Worktree, *, expected_source_tree_digest: str | None = None) -> None:
        head = self._run_git("-C", str(worktree.path), "rev-parse", "HEAD").stdout.strip().lower()
        if head != worktree.snapshot.commit.lower():
            raise CheckoutError(f"worktree HEAD mismatch: expected {worktree.snapshot.commit}, got {head}")
        if expected_source_tree_digest is not None:
            actual = source_tree_digest(worktree.path)
            if actual != expected_source_tree_digest:
                raise CheckoutError(
                    f"materialized worktree bytes differ from pinned source tree: expected {expected_source_tree_digest}, got {actual}"
                )
        else:
            status = self._run_git("-C", str(worktree.path), "status", "--porcelain=v1", "--untracked-files=all").stdout
            if status:
                raise CheckoutError("new worktree is not pristine before overlays")

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
