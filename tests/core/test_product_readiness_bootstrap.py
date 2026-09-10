from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_product_readiness_bootstrap_pins_latest_qualified_checkpoint_without_prompt() -> None:
    text = (ROOT / "START_PHASE3D_PRODUCT_READINESS.bat").read_text(encoding="utf-8")

    assert "7d865382446b2331641b582b8f5b9eaeceaed827" in text
    assert "b9f966bb48f10e904ae0086b48326875d6c634fc" not in text
    assert "run_product_readiness_windows_resilient.bat" in text
    assert "prepare_product_readiness_dsh_windows.bat" in text
    assert "choice /C YN" not in text
    assert "NO Y/N prompts" in text
    assert "NEVER starts the 370-pair paid A/B campaign" in text
