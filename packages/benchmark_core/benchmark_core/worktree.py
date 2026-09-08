"""Disposable detached worktrees with batched canonical materialization."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import tempfile
from .checkout import CheckoutError, RepositorySnapshot, source_tree_digest
from .git_objects import tree_entries, BlobReader


@dataclass(frozen=True)
class Worktree:
    path: Path
    snapshot: RepositorySnapshot
    linked: bool


class WorktreeManager:
    def __init__(self, runs_root):
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def _run_git(self, *args, check=True):
        return subprocess.run(["git", *args], check=check, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, shell=False)

    def _restore_canonical_git_bytes(self, path, snapshot):
        entries = tree_entries(snapshot.bare_repository, snapshot.commit)
        tracked_paths = {entry.path.decode("utf-8", "surrogateescape") for entry in entries}
        with BlobReader(snapshot.bare_repository) as reader:
            for entry in entries:
                relative = entry.path.decode("utf-8", "surrogateescape")
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise CheckoutError("Git tree path escapes worktree")
                target = path / relative_path
                # A tracked link must never redirect writes outside the owned worktree.
                if any(parent.is_symlink() for parent in target.parents if parent != path.parent):
                    raise CheckoutError("Linked canonical worktree parent")
                payload = reader.read(entry.oid, entry.size)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                if entry.mode == b"120000":
                    link_target = payload.decode("utf-8", "surrogateescape")
                    resolved_target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link_target))
                    target_is_directory = any(item.startswith(resolved_target.rstrip("/") + "/") for item in tracked_paths)
                    try:
                        target.symlink_to(link_target.replace("/", os.sep), target_is_directory=target_is_directory)
                        expected_target = (target.parent / link_target).resolve(strict=False)
                        if expected_target.exists() and not target.exists():
                            target.unlink()
                            target.symlink_to(expected_target, target_is_directory=target_is_directory)
                    except OSError as error:
                        raise CheckoutError(f"cannot materialize pinned symlink: {relative}") from error
                else:
                    target.write_bytes(payload)
                    if entry.mode == b"100755":
                        target.chmod(target.stat().st_mode | 0o111)

    def create(self, snapshot, destination=None, *, allow_copy_fallback=True):
        path = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="worktree-", dir=self.runs_root))
        if path.exists() and any(path.iterdir()):
            raise FileExistsError(f"worktree destination is not empty: {path}")
        if path.exists():
            path.rmdir()
        try:
            self._run_git("-c", "core.autocrlf=false", "-c", "core.symlinks=true", "--git-dir", str(snapshot.bare_repository),
                          "worktree", "add", "--detach", "--force", str(path), snapshot.commit)
            self._restore_canonical_git_bytes(path, snapshot)
            return Worktree(path, snapshot, True)
        except CheckoutError:
            self._run_git("--git-dir", str(snapshot.bare_repository), "worktree", "remove", "--force", str(path), check=False)
            shutil.rmtree(path, ignore_errors=True)
            raise
        except (OSError, subprocess.CalledProcessError) as error:
            if not allow_copy_fallback:
                raise CheckoutError(f"could not create linked worktree: {error}") from error
            try:
                self._run_git("clone", "--no-checkout", "--shared", str(snapshot.bare_repository), str(path))
                self._run_git("-C", str(path), "config", "core.autocrlf", "false")
                self._run_git("-C", str(path), "config", "core.symlinks", "true")
                self._run_git("-C", str(path), "checkout", "--detach", snapshot.commit)
                self._restore_canonical_git_bytes(path, snapshot)
            except (OSError, subprocess.CalledProcessError, CheckoutError) as fallback:
                shutil.rmtree(path, ignore_errors=True)
                raise CheckoutError(f"worktree and copy fallback failed: {fallback}") from fallback
            return Worktree(path, snapshot, False)

    def verify_pristine(self, worktree, *, expected_source_tree_digest=None):
        head = self._run_git("-C", str(worktree.path), "rev-parse", "HEAD").stdout.strip().lower()
        if head != worktree.snapshot.commit.lower():
            raise CheckoutError(f"worktree HEAD mismatch: expected {worktree.snapshot.commit}, got {head}")
        if expected_source_tree_digest is not None:
            actual = source_tree_digest(worktree.path)
            if actual != expected_source_tree_digest:
                raise CheckoutError(f"materialized worktree bytes differ from pinned source tree: expected {expected_source_tree_digest}, got {actual}")
        elif self._run_git("-C", str(worktree.path), "status", "--porcelain=v1", "--untracked-files=all").stdout:
            raise CheckoutError("new worktree is not pristine before overlays")

    def cleanup(self, worktree):
        item = worktree if isinstance(worktree, Worktree) else None
        path = item.path if item else Path(worktree)
        if item and item.linked:
            self._run_git("--git-dir", str(item.snapshot.bare_repository), "worktree", "remove", "--force", str(path), check=False)
            self._run_git("--git-dir", str(item.snapshot.bare_repository), "worktree", "prune", check=False)
        shutil.rmtree(path, ignore_errors=True)

    def recover(self, bare_repository):
        self._run_git("--git-dir", str(bare_repository), "worktree", "prune", check=False)

    @contextmanager
    def disposable(self, snapshot, destination=None, *, allow_copy_fallback=True):
        worktree = self.create(snapshot, destination, allow_copy_fallback=allow_copy_fallback)
        try:
            yield worktree
        finally:
            self.cleanup(worktree)

    materialize = disposable
