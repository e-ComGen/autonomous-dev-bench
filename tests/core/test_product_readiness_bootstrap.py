from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_product_readiness_bootstrap_pins_latest_qualified_checkpoint() -> None:
    text = (ROOT / "START_PHASE3D_PRODUCT_READINESS.bat").read_text(encoding="utf-8")

    assert "b9f966bb48f10e904ae0086b48326875d6c634fc" in text
    assert "ba6d8a0ad39d8aa9e8e140bed8be99609e00248c" not in text
    assert "product_readiness.bat" in text
    assert "max_tokens=8" in text
    assert "NEVER starts the 370-pair paid A/B campaign" in text
