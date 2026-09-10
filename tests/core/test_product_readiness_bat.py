from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_product_readiness_normalizes_trailing_script_backslash_before_git() -> None:
    text = (ROOT / "product_readiness.bat").read_text(encoding="utf-8")

    assert 'set "SOURCE_ROOT=%~dp0."' in text
    assert 'git -C "%SOURCE_ROOT%" rev-parse --verify HEAD' in text
    assert 'git -C "%~dp0" rev-parse' not in text
