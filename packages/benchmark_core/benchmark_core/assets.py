"""Locate public corpus manifests in a source checkout or installed wheel."""
from __future__ import annotations

from pathlib import Path
import sysconfig


def asset_path(relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("asset path must be relative and confined")
    source_root = Path(__file__).resolve().parents[3]
    source_candidate = source_root / relative
    if source_candidate.is_file():
        return source_candidate
    installed = Path(sysconfig.get_path("data")) / "share" / "autonomous-dev-bench" / relative
    if not installed.is_file():
        raise FileNotFoundError(relative_path)
    return installed
