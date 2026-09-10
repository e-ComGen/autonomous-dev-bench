from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_readiness_wrapper_keeps_wsl_alive_through_docker_gate() -> None:
    script = (ROOT / "run_product_readiness_windows_resilient.bat").read_text(encoding="utf-8")

    keepalive = 'start "AUTOBENCH_WSL_KEEPALIVE" /min wsl.exe -e bash -lc'
    docker_prepare = 'call "%SOURCE_ROOT%\\prepare_product_readiness_docker_windows.bat"'
    ordinary_probe = 'wsl.exe -e bash -lc "docker info >/dev/null 2>&1"'
    readiness = 'call "%SOURCE_ROOT%\\product_readiness.bat"'
    stop_signal = 'wsl.exe -e bash -lc "touch %STOP_FILE%"'

    positions = [
        script.index(keepalive),
        script.index(docker_prepare),
        script.index(ordinary_probe),
        script.index(readiness),
        script.index(stop_signal),
    ]
    assert positions == sorted(positions)
    assert "while [ ! -e %STOP_FILE% ]; do sleep 2; done" in script


def test_windows_readiness_wrapper_cannot_start_paid_campaign_or_model() -> None:
    script = (ROOT / "run_product_readiness_windows_resilient.bat").read_text(encoding="utf-8").casefold()

    assert "370-pair paid campaign" in script
    assert "harbor trials start" not in script
    assert "capture_deepseek_v4_live_usage.py" not in script
    assert "api.deepseek.com" not in script
