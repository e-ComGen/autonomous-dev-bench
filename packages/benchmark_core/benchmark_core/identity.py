"""Stable identities and canonical content hashing for benchmark specifications.

Only JSON-compatible values are accepted for hashing.  Mutable containers are
copied into immutable equivalents at schema boundaries, so a digest can never
change because a caller later mutates an input object.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Generic, TypeVar

JsonScalar = None | bool | int | float | str
# Recursive aliases are kept descriptive rather than enforced at runtime.
FrozenJson = Any
T = TypeVar("T")

_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._:/-]*[A-Za-z0-9])?$")


class FrozenDict(Mapping[str, T], Generic[T]):
    """A small immutable, hashable mapping with deterministic iteration order."""

    __slots__ = ("_items", "_dict", "_hash")

    def __init__(self, values: Mapping[str, T] | Iterator[tuple[str, T]] = ()) -> None:
        source = dict(values)
        if not all(isinstance(key, str) for key in source):
            raise TypeError("canonical mappings require string keys")
        self._items = tuple(sorted(source.items()))
        self._dict = dict(self._items)
        self._hash = hash(self._items)

    def __getitem__(self, key: str) -> T:
        return self._dict[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"FrozenDict({self._dict!r})"


def require_identifier(value: str, field_name: str = "identifier") -> str:
    """Validate a stable machine identifier without normalizing its meaning."""

    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a non-empty stable identifier")
    if value.casefold() == "latest":
        raise ValueError(f"{field_name} must be version-pinned; 'latest' is forbidden")
    return value


def require_nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def require_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def freeze_json(value: Any) -> FrozenJson:
    """Defensively copy JSON-like data into deeply immutable containers."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not canonical JSON")
        return value
    if isinstance(value, Enum):
        return freeze_json(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return FrozenDict((field.name, freeze_json(getattr(value, field.name))) for field in fields(value))
    if isinstance(value, Mapping):
        return FrozenDict((key, freeze_json(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _plain_json(value: Any) -> Any:
    frozen = freeze_json(value)
    if isinstance(frozen, FrozenDict):
        return {key: _plain_json(item) for key, item in frozen.items()}
    if isinstance(frozen, tuple):
        return [_plain_json(item) for item in frozen]
    return frozen


def canonical_json(value: Any) -> str:
    """Return UTF-8-independent RFC-8259 JSON with stable keys and separators."""

    return json.dumps(
        _plain_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True, order=True)
class Sha256Digest:
    """A lower-case, algorithm-qualified SHA-256 digest."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _SHA256_RE.fullmatch(self.value):
            raise ValueError("digest must be 'sha256:' followed by 64 lower-case hex characters")

    @classmethod
    def of(cls, value: Any) -> "Sha256Digest":
        payload = canonical_json(value).encode("utf-8")
        return cls(f"sha256:{hashlib.sha256(payload).hexdigest()}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class CommitPin:
    """An immutable Git commit pin; symbolic refs and abbreviated SHAs are invalid."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _COMMIT_RE.fullmatch(self.value):
            raise ValueError("commit pin must contain exactly 40 hexadecimal characters")
        object.__setattr__(self, "value", self.value.lower())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class VersionIdentity:
    """Logical identity plus explicit schema/item version and optional content pin."""

    logical_id: str
    version: str
    content_digest: Sha256Digest | None = None

    def __post_init__(self) -> None:
        require_identifier(self.logical_id, "logical_id")
        require_identifier(self.version, "version")
        if self.content_digest is not None and not isinstance(self.content_digest, Sha256Digest):
            object.__setattr__(self, "content_digest", Sha256Digest(str(self.content_digest)))

    def pinned(self, value: Any) -> "VersionIdentity":
        """Return the same logical version bound to canonical content."""

        return VersionIdentity(self.logical_id, self.version, Sha256Digest.of(value))


class CanonicalModel:
    """Mixin exposing deterministic serialization and a content identity."""

    def to_canonical_json(self) -> str:
        return canonical_json(self)

    @property
    def content_digest(self) -> Sha256Digest:
        return Sha256Digest.of(self)
