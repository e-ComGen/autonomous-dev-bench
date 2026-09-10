"""Outcome-blind static Zone scope for the first Stock-vs-ADCP experiment.

The selector uses only the public task instruction and the exact baseline Git
tree. It never reads SWE-bench gold/test patches, prior arm outputs, model output,
or repeat outcomes. Test files may influence neither write authority nor scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess
from typing import Iterable


SCOPE_POLICY = "phase3d-public-static-python-scope-v2"
MAX_SCOPE_FILES = 24
MAX_SCOPE_BYTES = 512 * 1024
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PATH_RE = re.compile(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.py)(?![A-Za-z0-9_./-])")
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "when", "then", "true", "false",
    "none", "does", "not", "into", "have", "has", "had", "are", "was", "were", "will",
    "would", "should", "could", "about", "using", "use", "used", "bug", "error", "issue",
    "expected", "actual", "output", "input", "python", "version", "return", "value", "values",
}
_TEST_PARTS = {"test", "tests", "testing", "testdata", "test_data"}


@dataclass(frozen=True, slots=True)
class ScopeSelection:
    policy: str
    baseline_commit: str
    instruction_sha256: str
    paths: tuple[str, ...]
    visible_bytes: int
    high_signal_tokens: tuple[str, ...]
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "policy": self.policy,
            "baseline_commit": self.baseline_commit,
            "instruction_sha256": self.instruction_sha256,
            "paths": list(self.paths),
            "visible_bytes": self.visible_bytes,
            "high_signal_tokens": list(self.high_signal_tokens),
            "digest": self.digest,
            "hidden_evaluation_material_used": False,
            "outcome_data_used": False,
        }


def _git(repo: str, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", repo, *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace")[-2000:])
    return completed.stdout


def _is_test_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    parts = {part.casefold() for part in parsed.parts[:-1]}
    name = parsed.name.casefold()
    return bool(parts & _TEST_PARTS) or name.startswith("test_") or name.endswith("_test.py")


def _tokens(instruction: str) -> tuple[tuple[str, int], ...]:
    weights: dict[str, int] = {}
    for raw in _TOKEN_RE.findall(instruction):
        token = raw.casefold()
        if len(token) < 4 or token in _STOP:
            continue
        weight = 1
        if "_" in raw:
            weight += 4
        if any(char.isupper() for char in raw[1:]):
            weight += 3
        if any(char.isdigit() for char in raw):
            weight += 1
        weights[token] = max(weights.get(token, 0), weight)
    # Bound grep fan-out deterministically. High-signal tokens first, then lexical.
    ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:32]
    return tuple(ordered)


def _inventory(repo: str, baseline: str) -> dict[str, int]:
    output = _git(repo, "ls-tree", "-rzl", "-r", baseline).decode("utf-8", "strict")
    result: dict[str, int] = {}
    for row in output.split("\0"):
        if not row:
            continue
        metadata, path = row.split("\t", 1)
        mode, kind, _oid, size = metadata.split()
        if mode != "100644" or kind != "blob" or not path.endswith(".py") or _is_test_path(path):
            continue
        try:
            byte_size = int(size)
        except ValueError:
            continue
        if 0 <= byte_size <= MAX_SCOPE_BYTES:
            result[path] = byte_size
    return result


def _grep_paths(repo: str, baseline: str, token: str) -> set[str]:
    completed = subprocess.run(
        ["git", "-C", repo, "grep", "-I", "-l", "-F", "-e", token, baseline, "--", "*.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.decode("utf-8", "replace")[-2000:])
    paths: set[str] = set()
    prefix = baseline + ":"
    for line in completed.stdout.decode("utf-8", "strict").splitlines():
        path = line[len(prefix):] if line.startswith(prefix) else line
        if path.endswith(".py") and not _is_test_path(path):
            paths.add(path)
    return paths


def select_write_scope(repo: str, instruction: str) -> ScopeSelection:
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("public task instruction is required")
    baseline = _git(repo, "rev-parse", "HEAD").decode("ascii").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", baseline) is None:
        raise ValueError("scope selector requires an exact SHA-1 baseline commit")

    inventory = _inventory(repo, baseline)
    if not inventory:
        raise ValueError("baseline contains no eligible production Python source files")
    tokens = _tokens(instruction)
    scores: dict[str, int] = {}

    explicit_paths = {match.group(1) for match in _PATH_RE.finditer(instruction)}
    for path in explicit_paths:
        if path in inventory:
            scores[path] = scores.get(path, 0) + 100_000

    lowered_instruction = instruction.casefold()
    for path in inventory:
        path_lower = path.casefold()
        stem = PurePosixPath(path).stem.casefold()
        if stem and stem in lowered_instruction and len(stem) >= 4:
            scores[path] = scores.get(path, 0) + 2_000
        for token, weight in tokens:
            if token in path_lower:
                scores[path] = scores.get(path, 0) + 200 * weight

    for token, weight in tokens:
        for path in _grep_paths(repo, baseline, token):
            if path in inventory:
                scores[path] = scores.get(path, 0) + 20 * weight

    ranked = sorted(
        (path for path, score in scores.items() if score > 0),
        key=lambda path: (-scores[path], inventory[path], path),
    )
    chosen: list[str] = []
    total = 0
    for path in ranked:
        size = inventory[path]
        if len(chosen) >= MAX_SCOPE_FILES:
            break
        if total + size > MAX_SCOPE_BYTES:
            continue
        chosen.append(path)
        total += size
    if not chosen:
        raise ValueError("public static scope selector found no bounded source candidate")

    chosen_tuple = tuple(sorted(chosen))
    instruction_sha = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    identity = {
        "policy": SCOPE_POLICY,
        "baseline_commit": baseline,
        "instruction_sha256": instruction_sha,
        "paths": list(chosen_tuple),
        "visible_bytes": total,
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ScopeSelection(
        policy=SCOPE_POLICY,
        baseline_commit=baseline,
        instruction_sha256=instruction_sha,
        paths=chosen_tuple,
        visible_bytes=total,
        high_signal_tokens=tuple(token for token, _ in tokens),
        digest=digest,
    )
