from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_live_usage_parity_verifier_rejects_non_live_capture_before_loading_assets(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps(
            {
                "request": {"model": "deepseek-v4-flash"},
                "usage": {"prompt_tokens": 1},
                "model_called": False,
                "provider": "deepseek-official",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "tools/verify_deepseek_v4_usage_parity.py",
            str(capture),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode != 0
    assert "capture must describe a real provider call" in result.stdout
