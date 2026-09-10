from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import tools.product_readiness as readiness
import tools.product_readiness_campaign as campaign


def _coverage(*, coverage_pass: bool = True, non_underestimate: bool = True) -> dict[str, object]:
    return {
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_COVERAGE",
        "status": "PASS" if coverage_pass else "FAIL",
        "qualification_mode": "CONSERVATIVE_REFERENCE_ENVELOPE_V1",
        "provider_prompt_tokens": 37,
        "no_effort_prefix_reference_input_tokens": 11,
        "reference_envelope_input_tokens": 90,
        "reference_effort_prefix_tokens": 79,
        "reservation_headroom_tokens": 53,
        "exact_match": False,
        "coverage_pass": coverage_pass,
        "request_policy_matches": True,
        "provider_above_lower_reference": True,
        "reference_envelope_non_underestimate": non_underestimate,
        "effort_prefix_structure_ok": True,
        "provider_usage_source_of_truth": True,
        "provider": "deepseek-official",
        "model_called": True,
    }


def test_live_parity_accepts_safe_coverage_without_fake_exact_match(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if "verify_deepseek_v4_usage_parity.py" in " ".join(command):
            stdout = json.dumps(_coverage())
        else:
            stdout = "PASS\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(readiness, "run", fake_run)

    detail = readiness.live_parity(tmp_path, "python", tmp_path / "artifacts")

    assert "provider_prompt_tokens=37" in detail
    assert "lower_reference=11" in detail
    assert "reservation=90" in detail
    assert "headroom=53" in detail
    assert "coverage=true" in detail
    assert any("capture_deepseek_v4_live_usage.py" in " ".join(call) for call in calls)
    assert any("verify_deepseek_v4_usage_parity.py" in " ".join(call) for call in calls)


def test_live_parity_rejects_reference_underestimate_even_if_verifier_process_exits_zero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    unsafe = _coverage()
    unsafe["reference_envelope_non_underestimate"] = False

    def fake_run(command, **kwargs):
        stdout = json.dumps(unsafe) if "verify_deepseek_v4_usage_parity.py" in " ".join(command) else "PASS\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(readiness, "run", fake_run)

    with pytest.raises(RuntimeError, match="not safely covered"):
        readiness.live_parity(tmp_path, "python", tmp_path / "artifacts")


def test_local_paid_preflight_promotes_only_structured_coverage_evidence(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bench"
    workspace = tmp_path / "workspace"
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True)
    root.mkdir()

    (artifacts / "PHASE3C3_REAL_ADCP_DSH.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "production_ready": True,
                "scope": "ADCP_REAL",
                "binding_id": "binding",
                "runtime_loaded": True,
                "real_deepseek_harness_subprocess": True,
                "paid_model_called": False,
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "deepseek-live-capture.json").write_text("{}", encoding="utf-8")
    (artifacts / "deepseek-estimator-cache").mkdir()

    for relative in campaign.REQUIRED_ADMISSION_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")

    coverage = _coverage()

    def fake_subprocess_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(coverage))

    monkeypatch.setattr(campaign.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(
        campaign.PaidAdmissionSnapshot,
        "from_repository",
        lambda path: SimpleNamespace(paid_ready=True, blockers=()),
    )

    ok, detail = campaign._local_paid_preflight(root, workspace)

    assert ok is True
    assert "usage coverage" in detail
    promoted = json.loads(
        (workspace / "paid-admission-overlay" / "DEEPSEEK_V4_ESTIMATOR.lock.json").read_text(encoding="utf-8")
    )
    evidence = promoted["local_product_readiness_evidence"]
    assert promoted["live_provider_prompt_usage_parity"] is True
    assert promoted["paid_ready"] is True
    assert evidence["coverage_pass"] is True
    assert evidence["provider_prompt_tokens"] == 37
    assert evidence["no_effort_prefix_reference_input_tokens"] == 11
    assert evidence["reference_envelope_input_tokens"] == 90
    assert "exact_match" not in evidence


def test_local_paid_preflight_rejects_failed_coverage(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bench"
    workspace = tmp_path / "workspace"
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True)
    root.mkdir()

    (artifacts / "PHASE3C3_REAL_ADCP_DSH.json").write_text(
        json.dumps({"status": "PASS", "production_ready": True}),
        encoding="utf-8",
    )
    (artifacts / "deepseek-live-capture.json").write_text("{}", encoding="utf-8")
    (artifacts / "deepseek-estimator-cache").mkdir()

    failed = _coverage(coverage_pass=False)

    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout=json.dumps(failed)),
    )

    ok, detail = campaign._local_paid_preflight(root, workspace)

    assert ok is False
    assert "not PASS" in detail
