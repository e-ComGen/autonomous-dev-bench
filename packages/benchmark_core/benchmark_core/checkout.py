"""Immutable Git acquisition; exact pins and batched canonical blob hashing."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import posixpath
import re
import subprocess
from .git_errors import CheckoutError, SourceTreeDigestMismatch
from .git_objects import BlobReader, tree_entries, digest_tree
from .git_transport import ensure_commit, run_git

_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    commit: str
    bare_repository: Path
    source_tree_digest: str


def _git(*args, cwd=None):
    return run_git(*args, cwd=cwd).stdout.strip()


def validate_pinned_commit(commit):
    if not _FULL_SHA.fullmatch(commit):
        raise ValueError("commit must be a full immutable 40- or 64-hex object id")
    return commit.lower()


def source_tree_digest(root):
    """Hash actual filesystem bytes with pinned mode/link semantics, unchanged wire digest."""
    base = Path(root)
    if not base.is_dir():
        raise ValueError(f"not a source directory: {base}")
    digest = hashlib.sha256()
    git_entries = {}
    if (base / ".git").exists():
        indexed = subprocess.run(["git", "-C", str(base), "ls-files", "-s", "-z"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout
        for entry in indexed.split(b"\0"):
            if entry:
                metadata, raw_path = entry.split(b"\t", 1)
                mode, object_id, _stage = metadata.split(b" ", 2)
                git_entries[raw_path.decode("utf-8", "surrogateescape")] = (mode, object_id)
    links = [entry[1] for entry in git_entries.values() if entry[0] == b"120000"]
    link_payloads = {}
    if links:
        bare = _git("-C", str(base), "rev-parse", "--absolute-git-dir")
        with BlobReader(bare) as reader:
            link_payloads = {oid: reader.read(oid) for oid in links}
    entries = []
    for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        entries.extend(Path(current, name) for name in sorted(files)
                       if not (Path(current) == base and name == ".git"))
        entries.extend(Path(current, name) for name in dirs if Path(current, name).is_symlink())
    for path in sorted(set(entries), key=lambda p: p.relative_to(base).as_posix().encode("utf-8")):
        relative_text = path.relative_to(base).as_posix()
        relative = relative_text.encode("utf-8")
        indexed_entry = git_entries.get(relative_text)
        indexed_mode = indexed_entry[0] if indexed_entry else None
        if indexed_mode == b"120000" or path.is_symlink():
            if indexed_mode == b"120000" and not path.is_symlink():
                raise ValueError(f"pinned Git symlink was materialized as a regular file: {relative_text}")
            kind = b"L"
            if indexed_entry:
                payload = link_payloads[indexed_entry[1]]
                expected_link = payload.decode("utf-8", "surrogateescape")
                if path.resolve(strict=False) != (path.parent / expected_link).resolve(strict=False):
                    raise ValueError(f"pinned symlink target mismatch: {relative_text}")
                resolved_target = posixpath.normpath(posixpath.join(posixpath.dirname(relative_text), expected_link))
                expected_directory = any(item.startswith(resolved_target.rstrip("/") + "/") for item in git_entries)
                if expected_directory and not path.is_dir():
                    raise ValueError(f"pinned directory symlink has incorrect filesystem semantics: {relative_text}")
            else:
                payload = os.readlink(path).encode("utf-8")
            mode = b"0"
        else:
            kind, payload = b"F", path.read_bytes()
            mode = b"1" if indexed_mode == b"100755" or (indexed_mode is None and path.stat().st_mode & 0o111) else b"0"
        for part in (kind, mode, relative, payload):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return "sha256:" + digest.hexdigest()


class SharedGitCache:
    """The existing shared bare cache; warm exact pins need no remote refresh."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _repository_path(self, repository):
        return self.root / hashlib.sha256(repository.encode("utf-8")).hexdigest() / "anchor.git"

    def ensure(self, repository, commit, *, expected_source_tree_digest=None, tree_validator=None, progress=None):
        commit = validate_pinned_commit(commit)
        if expected_source_tree_digest is not None and not _SHA256.fullmatch(expected_source_tree_digest):
            raise ValueError("expected source tree digest must be sha256:<64 lowercase hex>")
        bare = self._repository_path(repository)
        ensure_commit(bare, repository, commit, progress)
        if progress:
            progress("tree_inventory", commit=commit)
        entries = tree_entries(bare, commit)
        # Reject size/mode/scope-incompatible trees before blob hashing and worktree creation.
        if tree_validator:
            tree_validator(entries)
        if progress:
            progress("batch_hash", files=len(entries), source_bytes=sum(e.size for e in entries))
        actual_digest = digest_tree(bare, entries)
        if expected_source_tree_digest is not None and actual_digest != expected_source_tree_digest:
            raise SourceTreeDigestMismatch(f"source tree digest mismatch: expected {expected_source_tree_digest}, got {actual_digest}")
        return RepositorySnapshot(repository, commit, bare, actual_digest)

    acquire = ensure
