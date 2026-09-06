"""Immutable Git source acquisition and deterministic source hashing."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable

_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class CheckoutError(RuntimeError):
    pass


class SourceTreeDigestMismatch(CheckoutError):
    pass


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    commit: str
    bare_repository: Path
    source_tree_digest: str


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise CheckoutError(detail.strip()) from exc
    return completed.stdout.strip()


def validate_pinned_commit(commit: str) -> str:
    if not _FULL_SHA.fullmatch(commit):
        raise ValueError("commit must be a full immutable 40- or 64-hex object id")
    return commit.lower()


def source_tree_digest(root: str | os.PathLike[str]) -> str:
    """Hash names, kinds, executable bits, symlink targets and file bytes."""
    base = Path(root)
    if not base.is_dir():
        raise ValueError(f"not a source directory: {base}")
    digest = hashlib.sha256()
    git_modes: dict[str, bytes] = {}
    if (base / ".git").exists():
        indexed = subprocess.run(
            ["git", "-C", str(base), "ls-files", "-s", "-z"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        ).stdout
        for entry in indexed.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode = metadata.split(b" ", 1)[0]
            git_modes[raw_path.decode("utf-8", "surrogateescape")] = mode
    entries: list[Path] = []
    for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        entries.extend(Path(current, name) for name in sorted(files)
                       if not (Path(current) == base and name == ".git"))
        entries.extend(Path(current, name) for name in dirs if (Path(current, name).is_symlink()))
    for path in sorted(set(entries), key=lambda p: p.relative_to(base).as_posix().encode("utf-8")):
        relative_text = path.relative_to(base).as_posix()
        relative = relative_text.encode("utf-8")
        indexed_mode = git_modes.get(relative_text)
        if indexed_mode == b"120000" or path.is_symlink():
            kind = b"L"
            payload = os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes()
            mode = b"0"
        else:
            kind, payload = b"F", path.read_bytes()
            mode = b"1" if indexed_mode == b"100755" or (indexed_mode is None and path.stat().st_mode & 0o111) else b"0"
        for part in (kind, mode, relative, payload):
            digest.update(len(part).to_bytes(8, "big")); digest.update(part)
    return f"sha256:{digest.hexdigest()}"


class SharedGitCache:
    """A shared bare object cache; callers always request a pinned commit."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _repository_path(self, repository: str) -> Path:
        key = hashlib.sha256(repository.encode("utf-8")).hexdigest()
        return self.root / key / "anchor.git"

    def ensure(self, repository: str, commit: str, *,
               expected_source_tree_digest: str | None = None) -> RepositorySnapshot:
        commit = validate_pinned_commit(commit)
        if expected_source_tree_digest is not None and not _SHA256.fullmatch(expected_source_tree_digest):
            raise ValueError("expected source tree digest must be sha256:<64 lowercase hex>")
        bare = self._repository_path(repository)
        if not bare.exists():
            bare.parent.mkdir(parents=True, exist_ok=True)
            _git("clone", "--mirror", "--", repository, str(bare))
        else:
            actual_remote = _git("--git-dir", str(bare), "remote", "get-url", "origin")
            if actual_remote != repository:
                raise CheckoutError("shared cache repository identity mismatch")
        # Fetch advertised refs, then validate that the requested object is a commit.
        _git("--git-dir", str(bare), "fetch", "--prune", "origin")
        resolved = _git("--git-dir", str(bare), "rev-parse", f"{commit}^{{commit}}")
        if resolved.lower() != commit:
            raise CheckoutError(f"pinned commit resolved unexpectedly: {resolved}")
        listing = subprocess.run(
            ["git", "--git-dir", str(bare), "ls-tree", "-r", "-z", "--full-tree", commit],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        ).stdout
        digest = hashlib.sha256()
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            if kind != b"blob":
                raise CheckoutError(f"unsupported Git tree entry kind: {kind.decode('ascii', 'replace')}")
            payload = subprocess.run(
                ["git", "--git-dir", str(bare), "cat-file", "blob", object_id.decode("ascii")],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            ).stdout
            canonical_kind = b"L" if mode == b"120000" else b"F"
            executable = b"1" if mode == b"100755" else b"0"
            for part in (canonical_kind, executable, path, payload):
                digest.update(len(part).to_bytes(8, "big")); digest.update(part)
        actual_digest = f"sha256:{digest.hexdigest()}"
        if expected_source_tree_digest is not None and actual_digest != expected_source_tree_digest:
            raise SourceTreeDigestMismatch(
                f"source tree digest mismatch: expected {expected_source_tree_digest}, got {actual_digest}"
            )
        return RepositorySnapshot(repository, commit, bare, actual_digest)

    acquire = ensure
