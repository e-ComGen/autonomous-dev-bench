#!/usr/bin/env python3
from __future__ import annotations

import os

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_gateway import ModelGatewayConfig, ModelGatewayHTTPServer, ModelGatewayPricing, SharedModelGateway


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def main() -> int:
    gateway = SharedModelGateway(
        ModelBudgetGateway(
            BudgetManifest(
                input_token_cap=10000,
                output_token_cap=10000,
                total_model_token_cap=20000,
                max_requests=16,
                wall_time_seconds=300,
                patch_byte_cap=100000,
            )
        ),
        ModelGatewayConfig(
            client_token=required("GATEWAY_CLIENT_TOKEN"),
            upstream_base_url="http://fake-upstream:8000/v1",
            upstream_api_key=required("UPSTREAM_API_KEY"),
            expected_model="deepseek-v4-flash",
            pricing=ModelGatewayPricing(
                input_usd_per_million=0.0,
                output_usd_per_million=0.0,
                cache_input_usd_per_million=0.0,
            ),
            request_timeout_seconds=30,
        ),
    )
    server = ModelGatewayHTTPServer(("0.0.0.0", 8000), gateway)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
