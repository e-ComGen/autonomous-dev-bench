from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_docker_gate_is_self_healing_and_model_free() -> None:
    text = (ROOT / "prepare_product_readiness_docker_windows.bat").read_text(encoding="utf-8")

    assert 'wsl.exe -e bash -lc "command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1"' in text
    assert 'wsl.exe -u root -e bash -lc' in text
    assert 'Docker Desktop.exe' in text
    assert 'apt-get install -y docker.io' in text
    assert 'dockerd' in text
    assert 'docker info' in text

    lowered = text.lower()
    assert "deepseek_api_key" not in lowered
    assert "chat/completions" not in lowered
    assert "capture_deepseek" not in lowered
    assert "harbor trials start" not in lowered
    assert "370-pair" not in lowered
