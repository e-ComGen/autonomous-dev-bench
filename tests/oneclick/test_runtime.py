from pathlib import Path
import json
import os
import subprocess
import sys

from cli.oneclick.report import Report
from cli.oneclick.selftest import run_selftest
from tools.launcher_env import clean_environment

ROOT = Path(__file__).resolve().parents[2]


def test_child_environment_does_not_include_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-forward")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-forward")
    monkeypatch.setenv("GITHUB_TOKEN", "read-only-test")
    monkeypatch.setenv("PYTHONSTARTUP", "untrusted.py")
    plain = clean_environment(tmp_path)
    assert "DEEPSEEK_API_KEY" not in plain
    assert "AWS_SECRET_ACCESS_KEY" not in plain
    assert "GITHUB_TOKEN" not in plain
    assert "PYTHONSTARTUP" not in plain
    assert clean_environment(tmp_path, github=True)["GITHUB_TOKEN"] == "read-only-test"


def test_summary_is_small_and_cas_verified(tmp_path):
    report = Report(tmp_path, "test")
    path = report.save({"status": "CHECKED", "coding_quality_measured": False})
    pointer = json.loads((tmp_path / ".bench/latest.json").read_text())
    assert report.cas.verify(pointer["cas_ref"])
    assert json.loads(path.read_text())["live_model_called"] is False


def test_real_bundled_negative_control_without_model(tmp_path, monkeypatch):
    environment = clean_environment(tmp_path)
    for key in list(os.environ):
        monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    report = Report(tmp_path, "control")
    result = run_selftest(ROOT, report)
    assert result["status"] == "SELFTEST_OK"
    assert result["negative_control_detected"]
    assert [item["counts"]["failures"] for item in result["stages"]] == [0, 1, 0]
    assert not (report.directory / "selftest-source").exists()


def test_cli_does_not_need_an_installed_benchmark_package(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/bench.py"), "plan",
                             "--config", str(ROOT / "BENCHMARK.toml")],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "PLAN_ONLY" in result.stdout
    assert len(result.stdout.splitlines()) <= 6


def test_conflicting_network_flags_fail():
    result = subprocess.run([sys.executable, str(ROOT / "tools/bench.py"), "projects", "--offline", "--allow-network"],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
