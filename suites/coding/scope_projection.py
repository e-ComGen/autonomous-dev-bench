"""Outcome-blind task scope projection for the Phase 3D ADCP arm.

The selector consumes only the public problem statement and the exact baseline
repository. It never receives SWE-bench gold/test patches, FAIL_TO_PASS lists or
official grading output. The resulting WRITE set is deliberately broader than
the small static READ preload; normal DSH tools may inspect the disposable full
repository sandbox, while authoritative mutations remain restricted to WRITE.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Iterable


SCOPE_POLICY = "phase3d-public-lexical-scope-v1"
DEFAULT_MAX_WRITE_PATHS = 512
DEFAULT_MAX_READ_PATHS = 32
DEFAULT_MAX_READ_BYTES = 65536
MAX_GREP_TOKENS = 24

_TEXT_SUFFIXES = frozenset(
    {
        ".py", ".pyi", ".pyx", ".pxd", ".pxi",
        ".rst", ".md", ".txt", ".toml", ".cfg", ".ini",
        ".yaml", ".yml", ".json", ".xml", ".html", ".htm",
        ".jinja", ".jinja2", ".js", ".ts", ".css", ".scss",
        ".sh", ".bash", ".bat", ".ps1", ".c", ".h", ".cpp", ".hpp",
    }
)
_TEXT_NAMES = frozenset(
    {
        "makefile", "dockerfile", "manifest.in", "tox.ini", "setup.cfg",
        "pyproject.toml", "requirements.txt", "conftest.py",
    }
)
_STOPWORDS = frozenset(
    {
        "about", "after", "again", "also", "because", "before", "being", "between",
        "change", "changes", "class", "could", "does", "error", "expected", "from",
        "function", "have", "into", "issue", "method", "module", "must", "need", "only",
        "please", "return", "should", "that", "their", "there", "these", "this", "using",
        "value", "when", "where", "which", "while", "with", "without", "would",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{2,}")
_PATH_RE = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+")
_BACKTICK_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True, slots=True)
class ScopeProjection:
    policy: str
    baseline_commit: str
    problem_sha256: str
    tokens: tuple[str, ...]
    write_paths: tuple[str, ...]
    read_paths: tuple[str, ...]
    read_bytes: int

    @property
    def identity(self) -> str:
        parts = [
            self.policy,
            self.baseline_commit,
            self.problem_sha256,
            "\0".join(self.tokens),
            "\0".join(self.write_paths),
            "\0".join(self.read_paths),
            str(self.read_bytes),
        ]
        return "sha256:" + hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _git(root: Path, *args: str, input_bytes: bytes | None = None, ok=(0,)) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), "-c", "core.autocrlf=false", *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if completed.returncode not in ok:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            + completed.stderr.decode("utf-8", "replace")[-2000:]
        )
    return completed.stdout


def _tracked_entries(root: Path) -> tuple[tuple[str, str, str], ...]:
    raw = _git(root, "ls-files", "-s", "-z")
    result = []
    for row in raw.split(b"\0"):
        if not row:
            continue
        metadata, path_raw = row.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise ValueError("scope projection refuses an unmerged baseline")
        path = path_raw.decode("utf-8")
        parsed = PurePosixPath(path)
        if str(parsed) != path or parsed.is_absolute() or ".." in parsed.parts or ".git" in parsed.parts:
            raise ValueError(f"unsafe tracked path in baseline: {path!r}")
        result.append((path, mode, oid))
    return tuple(result)


def _looks_textual(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.casefold()
    return name in _TEXT_NAMES or pure.suffix.casefold() in _TEXT_SUFFIXES


def _candidate_entries(root: Path) -> tuple[tuple[str, str], ...]:
    # ADCP's current authoritative writer intentionally supports only regular
    # non-executable text replacements. Binary text-looking files are rejected
    # again at import; this selector never weakens that final guard.
    return tuple(
        (path, oid)
        for path, mode, oid in _tracked_entries(root)
        if mode == "100644" and _looks_textual(path)
    )


def _blob_sizes(root: Path, entries: Iterable[tuple[str, str]]) -> dict[str, int]:
    pairs = tuple(entries)
    if not pairs:
        return {}
    raw = _git(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_bytes="".join(oid + "\n" for _, oid in pairs).encode("ascii"),
    ).decode("ascii")
    by_oid: dict[str, int] = {}
    for line in raw.splitlines():
        oid, kind, size = line.split()
        if kind != "blob":
            raise ValueError("tracked regular file does not resolve to a blob")
        by_oid[oid] = int(size)
    return {path: by_oid[oid] for path, oid in pairs}


def _tokens(problem: str) -> tuple[str, ...]:
    if not isinstance(problem, str) or not problem.strip():
        raise ValueError("public problem statement must be non-empty")
    boosted = {token.casefold() for segment in _BACKTICK_RE.findall(problem) for token in _TOKEN_RE.findall(segment)}
    score: dict[str, int] = {}
    for raw in _TOKEN_RE.findall(problem):
        original = raw
        pieces = [raw, *re.split(r"[_.-]+", raw)]
        # CamelCase identifiers produce useful repository search terms too.
        pieces += re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", raw)
        for piece in pieces:
            token = piece.casefold().strip("._-")
            if len(token) < 3 or token in _STOPWORDS or token.isdigit():
                continue
            weight = 1
            if token in boosted:
                weight += 8
            if "_" in original or "." in original or "-" in original:
                weight += 3
            if len(token) >= 8:
                weight += 2
            score[token] = score.get(token, 0) + weight
    return tuple(token for token, _ in sorted(score.items(), key=lambda item: (-item[1], -len(item[0]), item[0])))


def _direct_paths(problem: str, candidates: set[str]) -> set[str]:
    normalized = {path.casefold(): path for path in candidates}
    result = set()
    for raw in _PATH_RE.findall(problem):
        value = raw.strip("`'\".,:;()[]{}")
        match = normalized.get(value.casefold())
        if match is not None:
            result.add(match)
    return result


def _grep_files(root: Path, token: str) -> tuple[str, ...]:
    # -I ignores binary matches; -l bounds output to paths; --full-name makes
    # path identity independent of the caller's working directory.
    raw = _git(root, "grep", "-I", "-i", "-l", "-F", "-e", token, "HEAD", "--", ok=(0, 1))
    if not raw:
        return ()
    prefix = "HEAD:"
    result = []
    for line in raw.decode("utf-8", "replace").splitlines():
        path = line[len(prefix):] if line.startswith(prefix) else line
        if path:
            result.append(path)
    return tuple(sorted(set(result)))


def project_task_scope(
    repository: str | Path,
    problem_statement: str,
    *,
    max_write_paths: int = DEFAULT_MAX_WRITE_PATHS,
    max_read_paths: int = DEFAULT_MAX_READ_PATHS,
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> ScopeProjection:
    root = Path(repository).resolve(strict=True)
    for name, value in (
        ("max_write_paths", max_write_paths),
        ("max_read_paths", max_read_paths),
        ("max_read_bytes", max_read_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be positive")

    baseline = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if len(baseline) != 40:
        raise ValueError("baseline HEAD is not a full SHA-1 commit")
    candidates = _candidate_entries(root)
    if not candidates:
        raise ValueError("baseline contains no eligible writable text files")
    candidate_paths = {path for path, _ in candidates}
    sizes = _blob_sizes(root, candidates)
    tokens = _tokens(problem_statement)
    direct = _direct_paths(problem_statement, candidate_paths)

    scores = {path: 0 for path in candidate_paths}
    for path in candidate_paths:
        lower = path.casefold()
        basename = PurePosixPath(path).name.casefold()
        stem = PurePosixPath(path).stem.casefold()
        depth = len(PurePosixPath(path).parts)
        # Deterministic mild source-code prior only breaks otherwise-uninformed
        # ties; task-specific evidence below dominates it.
        scores[path] += 8 if PurePosixPath(path).suffix.casefold() in {".py", ".pyi", ".pyx"} else 0
        scores[path] += max(0, 4 - min(depth, 4))
        for token in tokens[:MAX_GREP_TOKENS]:
            if stem == token or basename == token:
                scores[path] += 400
            elif token in lower:
                scores[path] += 40
    for path in direct:
        scores[path] += 100000

    for token in tokens[:MAX_GREP_TOKENS]:
        matches = tuple(path for path in _grep_files(root, token) if path in candidate_paths)
        if not matches:
            continue
        # Rare terms carry more scoping evidence than repository-wide prose.
        rarity = max(1, 1200 // len(matches))
        for path in matches:
            scores[path] += rarity

    ranked = tuple(
        sorted(
            candidate_paths,
            key=lambda path: (
                -scores[path],
                len(PurePosixPath(path).parts),
                path.casefold(),
                path,
            ),
        )
    )
    write_paths = ranked[:max_write_paths]
    if not write_paths:
        raise ValueError("scope projection produced no writable paths")

    read: list[str] = []
    read_bytes = 0
    for path in ranked:
        if len(read) >= max_read_paths:
            break
        size = sizes[path]
        if size > max_read_bytes:
            continue
        if read_bytes + size > max_read_bytes:
            continue
        read.append(path)
        read_bytes += size
    if not read:
        raise ValueError("scope projection cannot fit any text file in the static read budget")

    return ScopeProjection(
        policy=SCOPE_POLICY,
        baseline_commit=baseline,
        problem_sha256=hashlib.sha256(problem_statement.encode("utf-8")).hexdigest(),
        tokens=tokens,
        write_paths=tuple(write_paths),
        read_paths=tuple(read),
        read_bytes=read_bytes,
    )
