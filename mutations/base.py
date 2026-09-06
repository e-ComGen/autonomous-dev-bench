"""Safe, deterministic mutation primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import random
import tempfile
from typing import Mapping, Protocol, runtime_checkable

from benchmark_core.identity import FrozenDict, freeze_json, require_identifier
from benchmark_core.result import RunStatus


@dataclass(frozen=True, slots=True)
class MutationDescriptor:
    mutation_id: str
    category: str
    semantic_intent: str
    applicable_project_tags: tuple[str, ...] = ()
    precondition_ids: tuple[str, ...] = ()
    supported_suite_ids: tuple[str, ...] = ()
    reversible: bool = True
    deterministic_from_seed: bool = True
    preserved_properties: tuple[str, ...] = ()
    intentionally_changed_properties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.mutation_id, "mutation_id")
        require_identifier(self.category, "category")
        if not self.semantic_intent.strip():
            raise ValueError("semantic_intent must be non-empty")
        for field_name in ("applicable_project_tags", "precondition_ids", "supported_suite_ids"):
            values = tuple(getattr(self, field_name))
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
            for value in values:
                require_identifier(value, field_name)
            object.__setattr__(self, field_name, values)
        for field_name in ("preserved_properties", "intentionally_changed_properties"):
            values = tuple(getattr(self, field_name))
            if len(set(values)) != len(values) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain unique non-empty strings")
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class ApplicationEvidence:
    mutation_id: str
    seed: int
    status: RunStatus | str
    changed_paths: tuple[str, ...] = ()
    before_digests: Mapping[str, str] = field(default_factory=FrozenDict)
    after_digests: Mapping[str, str] = field(default_factory=FrozenDict)
    preconditions: Mapping[str, bool] = field(default_factory=FrozenDict)
    details: Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        require_identifier(self.mutation_id, "mutation_id")
        object.__setattr__(self, "status", RunStatus(self.status))
        object.__setattr__(self, "changed_paths", tuple(self.changed_paths))
        object.__setattr__(self, "before_digests", freeze_json(self.before_digests))
        object.__setattr__(self, "after_digests", freeze_json(self.after_digests))
        object.__setattr__(self, "preconditions", freeze_json(self.preconditions))
        object.__setattr__(self, "details", freeze_json(self.details))

    @property
    def verified(self) -> bool:
        return self.status is RunStatus.PASS


MutationApplicationEvidence = ApplicationEvidence


@runtime_checkable
class MutationRecipe(Protocol):
    descriptor: MutationDescriptor

    def apply(self, workspace: str | Path, parameters: Mapping[str, object], seed: int = 0) -> ApplicationEvidence: ...
    def verify_applied(self, workspace: str | Path, evidence: ApplicationEvidence, parameters: Mapping[str, object]) -> bool: ...


class UnsafeWorkspacePath(ValueError):
    pass


def safe_workspace_path(workspace: str | Path, relative_path: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a non-symlink workspace-relative path and reject traversal."""
    root = Path(workspace).resolve(strict=True)
    rel = Path(relative_path)
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):
        raise UnsafeWorkspacePath(f"unsafe workspace-relative path: {relative_path!s}")
    candidate = root.joinpath(rel)
    current = root
    for part in rel.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise UnsafeWorkspacePath(f"symlink path component is forbidden: {relative_path!s}")
    resolved_parent = candidate.parent.resolve(strict=True)
    if root != resolved_parent and root not in resolved_parent.parents:
        raise UnsafeWorkspacePath(f"path escapes workspace: {relative_path!s}")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def atomic_write_text(workspace: str | Path, relative_path: str | Path, text: str) -> Path:
    """Atomically replace one UTF-8 file inside the workspace."""
    target = safe_workspace_path(workspace, relative_path)
    target.parent.mkdir(parents=False, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def seeded_choice(values: tuple[str, ...] | list[str], seed: int) -> str:
    if not values:
        raise ValueError("cannot choose from an empty sequence")
    return random.Random(seed).choice(sorted(values))
