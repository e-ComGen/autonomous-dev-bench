"""Run one fresh exact-token budget proxy for a single Phase 3D arm.

The upstream DeepSeek credential lives only in this sidecar. Agent containers get
only the random client token and service URL. Token admission uses the immutable
DeepSeek-V4 encoder/tokenizer assets already qualified by product readiness.
"""
from __future__ import annotations

import os
from pathlib import Path

from benchmark_core.deepseek_v4_estimator import DEEPSEEK_V4_MODEL, DeepSeekV4RequestEstimator
from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_proxy import BudgetedModelProxyCore
from benchmark_core.model_proxy_http import BudgetProxyHttpConfig, BudgetProxyHttpServer


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def positive_int(name: str) -> int:
    raw = required(name)
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def main() -> int:
    if os.environ.get("AUTOBENCH_PHASE3D_PAID_EXPERIMENT") != "1":
        raise ValueError("Phase 3D paid proxy requires explicit paid-experiment mode")
    model = required("AUTOBENCH_MODEL")
    if model != DEEPSEEK_V4_MODEL:
        raise ValueError(f"proxy model mismatch: expected {DEEPSEEK_V4_MODEL}, got {model}")

    cache_dir = Path(required("AUTOBENCH_DEEPSEEK_ESTIMATOR_CACHE")).resolve()
    estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
        expected_model=model,
        cache_dir=cache_dir,
        allow_network=False,
    )
    budget = BudgetManifest(
        input_token_cap=positive_int("AUTOBENCH_INPUT_TOKEN_CAP"),
        output_token_cap=positive_int("AUTOBENCH_OUTPUT_TOKEN_CAP"),
        total_model_token_cap=positive_int("AUTOBENCH_TOTAL_MODEL_TOKEN_CAP"),
        max_requests=positive_int("AUTOBENCH_MAX_REQUESTS"),
        wall_time_seconds=positive_int("AUTOBENCH_WALL_TIME_SECONDS"),
        patch_byte_cap=positive_int("AUTOBENCH_PATCH_BYTE_CAP"),
    )
    core = BudgetedModelProxyCore(
        ModelBudgetGateway(budget),
        estimator,
        expected_model=model,
    )
    upstream = required("AUTOBENCH_DEEPSEEK_UPSTREAM_BASE_URL").rstrip("/") + "/chat/completions"
    config = BudgetProxyHttpConfig(
        upstream_chat_completions_url=upstream,
        upstream_api_key=required("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"),
        client_api_key=required("AUTOBENCH_MODEL_PROXY_TOKEN"),
        upstream_timeout_seconds=float(os.environ.get("AUTOBENCH_UPSTREAM_TIMEOUT_SECONDS", "120")),
    )
    host = os.environ.get("AUTOBENCH_PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("AUTOBENCH_PROXY_PORT", "8000"))
    server = BudgetProxyHttpServer((host, port), core, config)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
