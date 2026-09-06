from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from cli.zoning_preview import run_project_preview


@pytest.mark.skipif(os.environ.get("AUTODEV_RUN_LOCAL_INTEGRATION") != "1", reason="opt-in local production package")
def test_real_pluggy_full_project_preview_is_stable(tmp_path: Path) -> None:
    source = os.environ.get("AUTODEV_AUTOZONING_SOURCE")
    if not source:
        pytest.skip("AUTODEV_AUTOZONING_SOURCE is not configured")
    report = run_project_preview(
        "pluggy", production_source=Path(source), python_executable=Path(sys.executable),
        cache_root=tmp_path / "cache", output_dir=tmp_path / "reports", runs=2, timeout=240,
    )
    assert report["status"] == "PASS"
    assert report["authority"] == "NONE" and report["advisory"] is True
    assert report["scope"] == {"mode": "FULL", "paths": []}
    assert report["stability"]["distinct_analysis_digests"] == 1
    assert report["proposal"]["coverage"]["parsed_files"] >= 20
    assert (tmp_path / "reports" / "pluggy.pinned_001.zoning-preview.v1.json").is_file()
    assert (tmp_path / "reports" / "pluggy.pinned_001.zoning-preview.v1.raw.run-2.json").is_file()
