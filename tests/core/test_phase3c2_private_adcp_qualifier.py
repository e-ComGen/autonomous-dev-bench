from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qualify_phase3c_private_adcp import (
    ADCP_COMMIT,
    ADCP_INTEGRATION,
    ADCP_REPOSITORY,
    ADCP_RUNTIME,
    qualify,
)


def test_qualifier_target_matches_public_adcp_lock() -> None:
    lock = json.loads(Path("ADCP.lock.json").read_text(encoding="utf-8"))
    assert lock["repository"] == ADCP_REPOSITORY
    assert lock["commit"] == ADCP_COMMIT
    assert lock["runtime"] == ADCP_RUNTIME
    assert lock["integration"] == ADCP_INTEGRATION


def test_missing_private_checkout_fails_before_importing_adcp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checkout missing"):
        qualify(tmp_path / "does-not-exist")


def test_non_git_directory_fails_closed(tmp_path: Path) -> None:
    checkout = tmp_path / "adcp"
    checkout.mkdir()
    with pytest.raises(RuntimeError):
        qualify(checkout)
