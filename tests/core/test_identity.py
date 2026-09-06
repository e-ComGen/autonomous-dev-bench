from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "benchmark_core"))

from benchmark_core.identity import CommitPin, FrozenDict, Sha256Digest, VersionIdentity, canonical_json, freeze_json


def test_canonical_json_and_digest_are_order_independent() -> None:
    left = {"z": [3, {"b": 2, "a": 1}], "unicode": "λ"}
    right = {"unicode": "λ", "z": (3, {"a": 1, "b": 2})}
    assert canonical_json(left) == canonical_json(right)
    assert Sha256Digest.of(left) == Sha256Digest.of(right)
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_freeze_json_is_deep_and_defensive() -> None:
    original = {"nested": [{"x": 1}]}
    frozen = freeze_json(original)
    original["nested"][0]["x"] = 9
    assert isinstance(frozen, FrozenDict)
    assert frozen["nested"][0]["x"] == 1
    with pytest.raises(TypeError):
        frozen["new"] = 2  # type: ignore[index]


def test_commit_pin_requires_full_sha_and_rejects_latest() -> None:
    pin = CommitPin("A" * 40)
    assert pin.value == "a" * 40
    for invalid in ("latest", "main", "a" * 39, "a" * 41, "g" * 40):
        with pytest.raises(ValueError):
            CommitPin(invalid)


def test_digest_and_version_identity_are_strict_and_frozen() -> None:
    digest = Sha256Digest.of({"x": True})
    identity = VersionIdentity("httpx.task", "v1", digest)
    assert str(digest).startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        identity.version = "v2"  # type: ignore[misc]
    with pytest.raises(ValueError):
        VersionIdentity("thing", "latest")
    with pytest.raises(ValueError):
        Sha256Digest("sha256:" + "A" * 64)
