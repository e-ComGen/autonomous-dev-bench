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


def _live_capture(*, prompt_tokens: int = 37, reasoning_effort: str = "high") -> dict[str, object]:
    return {
        "request": {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Answer briefly."},
                {"role": "user", "content": "Reply with OK."},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "enabled"},
            "reasoning_effort": reasoning_effort,
            "max_tokens": 8,
        },
        "usage": {"prompt_tokens": prompt_tokens},
        "model_called": True,
        "provider": "deepseek-official",
    }


def _install_estimator(monkeypatch, *, low: int, high: int) -> None:
    class FakeEstimator:
        def estimate(self, request):
            effort = request.get("reasoning_effort")
            return SimpleNamespace(input_tokens=low if effort == "low" else high)

    monkeypatch.setattr(
        parity_tool.DeepSeekV4RequestEstimator,
        "from_huggingface_revision",
        lambda **kwargs: FakeEstimator(),
    )


def test_exact_fixed_probe_is_inside_safe_reference_envelope(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=37, high=90)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=37), tmp_path)

    assert result["scope"] == "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_COVERAGE"
    assert result["status"] == "PASS"
    assert result["qualification_mode"] == "CONSERVATIVE_REFERENCE_ENVELOPE_V1"
    assert result["request_policy_matches"] is True
    assert result["estimated_input_tokens"] == 37
    assert result["provider_accounted_input_tokens"] == 37
    assert result["no_effort_prefix_reference_input_tokens"] == 37
    assert result["reference_envelope_input_tokens"] == 90
    assert result["provider_prompt_tokens"] == 37
    assert result["reference_effort_prefix_tokens"] == 53
    assert result["reservation_headroom_tokens"] == 53
    assert result["exact_match"] is True
    assert result["coverage_pass"] is True
    assert result["reference_envelope_non_underestimate"] is True
    assert result["provider_usage_source_of_truth"] is True


def test_coverage_can_pass_while_exact_probe_parity_is_false(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=37, high=90)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=40), tmp_path)

    assert result["status"] == "PASS"
    assert result["coverage_pass"] is True
    assert result["exact_match"] is False
    assert result["provider_overhead_vs_lower_reference"] == 3
    assert result["reservation_headroom_tokens"] == 50


def test_live_usage_fails_when_provider_is_below_structural_reference(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=38, high=91)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=37), tmp_path)

    assert result["status"] == "FAIL"
    assert result["coverage_pass"] is False
    assert result["provider_above_lower_reference"] is False
    assert result["exact_match"] is False


def test_live_usage_fails_closed_if_reference_envelope_underestimates_provider(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=37, high=40)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=41), tmp_path)

    assert result["status"] == "FAIL"
    assert result["coverage_pass"] is False
    assert result["reference_envelope_non_underestimate"] is False


def test_live_usage_fails_closed_when_high_effort_prefix_is_not_positive(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=37, high=37)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=37), tmp_path)

    assert result["status"] == "FAIL"
    assert result["effort_prefix_structure_ok"] is False


def test_live_usage_fails_closed_when_request_policy_differs(tmp_path: Path, monkeypatch) -> None:
    _install_estimator(monkeypatch, low=37, high=90)

    result = parity_tool.verify_capture(_live_capture(prompt_tokens=37, reasoning_effort="max"), tmp_path)

    assert result["status"] == "FAIL"
    assert result["request_policy_matches"] is False


def test_no_effort_prefix_projection_only_changes_reasoning_effort_control() -> None:
    original = _live_capture()["request"]
    assert isinstance(original, dict)

    adjusted = parity_tool._no_effort_prefix_request(original)

    assert adjusted["reasoning_effort"] == "low"
    restored = dict(adjusted)
    restored["reasoning_effort"] = "high"
    assert restored == original
    assert adjusted is not original
