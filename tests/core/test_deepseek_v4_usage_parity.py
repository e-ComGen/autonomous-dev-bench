from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import tools.verify_deepseek_v4_usage_parity as parity_tool


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


def test_estimator_console_noise_is_suppressed_for_json_cli_contract(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class FakeEstimator:
        def estimate(self, request):
            print("estimator-stdout-noise")
            print("estimator-stderr-noise", file=sys.stderr)
            return SimpleNamespace(input_tokens=7)

    def fake_factory(*, cache_dir: Path, allow_network: bool):
        assert cache_dir == tmp_path
        assert allow_network is False
        print("factory-stdout-noise")
        print("factory-stderr-noise", file=sys.stderr)
        return FakeEstimator()

    monkeypatch.setattr(
        parity_tool.DeepSeekV4RequestEstimator,
        "from_huggingface_revision",
        fake_factory,
    )

    estimated = parity_tool._estimate_without_console_noise({"model": "deepseek-v4-flash"}, tmp_path)
    captured = capsys.readouterr()

    assert estimated.input_tokens == 7
    assert captured.out == ""
    assert captured.err == ""
