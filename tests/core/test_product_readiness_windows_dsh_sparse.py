from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_dsh_preflight_uses_exact_sparse_pin_before_checkout() -> None:
    text = (ROOT / "prepare_product_readiness_dsh_windows.bat").read_text(encoding="utf-8")
    lock = json.loads((ROOT / "DEEPSEEK_HARNESS.lock.json").read_text(encoding="utf-8"))
    expected = lock["qualification_reference"]["commit"]

    assert f'set "DSH_SHA={expected}"' in text
    assert 'set "SOURCE_ROOT=%~dp0."' in text
    assert 'config core.longpaths true' in text
    assert 'config core.autocrlf false' in text
    assert 'sparse-checkout init --no-cone' in text
    assert 'sparse-checkout set --no-cone /README.md' in text
    assert text.index('sparse-checkout set --no-cone /README.md') < text.index('checkout --detach --force "%DSH_SHA%"')
    assert 'rev-parse HEAD' in text
    assert 'status --porcelain --untracked-files=all' in text
