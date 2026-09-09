from __future__ import annotations

import json
from pathlib import Path

from benchmark_core.deepseek_v4_estimator import (
    DEEPSEEK_V4_ENCODING_FILE,
    DEEPSEEK_V4_MODEL,
    DEEPSEEK_V4_REPO_ID,
    DEEPSEEK_V4_REVISION,
)


ROOT = Path(__file__).resolve().parents[2]


def test_estimator_lock_matches_runtime_identity_and_preserves_paid_blocker() -> None:
    lock = json.loads((ROOT / "DEEPSEEK_V4_ESTIMATOR.lock.json").read_text(encoding="utf-8"))

    assert lock["model_route"] == DEEPSEEK_V4_MODEL
    assert lock["source"]["repo_id"] == DEEPSEEK_V4_REPO_ID
    assert lock["source"]["revision"] == DEEPSEEK_V4_REVISION
    assert lock["source"]["encoding_file"] == DEEPSEEK_V4_ENCODING_FILE
    assert lock["network_policy"]["paid_trial_default_local_only"] is True
    assert lock["provider_usage_source_of_truth"] is True
    assert lock["live_provider_prompt_usage_parity"] is False
    assert lock["paid_ready"] is False
