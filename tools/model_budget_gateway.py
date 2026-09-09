"""Run one authenticated shared model-budget gateway for one benchmark arm/trial."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "benchmark_core")]

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayHTTPServer,
    ModelGatewayPricing,
    SharedModelGateway,
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--advertise-base-url", help="Task-visible OpenAI-compatible base URL; defaults to the bound host/port + /v1")
    parser.add_argument("--client-token-env", default="AUTOBENCH_MODEL_GATEWAY_TOKEN")
    parser.add_argument("--upstream-api-key-env", default="AUTOBENCH_UPSTREAM_MODEL_API_KEY")
    parser.add_argument("--upstream-base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--input-token-cap", type=int, required=True)
    parser.add_argument("--output-token-cap", type=int, required=True)
    parser.add_argument("--total-model-token-cap", type=int, required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--wall-time-seconds", type=int, required=True)
    parser.add_argument("--patch-byte-cap", type=int, required=True)
    parser.add_argument("--input-usd-per-million", type=float, required=True)
    parser.add_argument("--output-usd-per-million", type=float, required=True)
    parser.add_argument("--cache-input-usd-per-million", type=float, required=True)
    parser.add_argument("--request-timeout-seconds", type=int, default=120)
    parser.add_argument("--ready-file", type=Path, help="Atomically emit task-visible gateway URLs after binding")
    args = parser.parse_args()

    budget = BudgetManifest(
        input_token_cap=args.input_token_cap,
        output_token_cap=args.output_token_cap,
        total_model_token_cap=args.total_model_token_cap,
        max_requests=args.max_requests,
        wall_time_seconds=args.wall_time_seconds,
        patch_byte_cap=args.patch_byte_cap,
    )
    gateway = SharedModelGateway(
        ModelBudgetGateway(budget),
        ModelGatewayConfig(
            client_token=required_env(args.client_token_env),
            upstream_base_url=args.upstream_base_url,
            upstream_api_key=required_env(args.upstream_api_key_env),
            expected_model=args.model,
            pricing=ModelGatewayPricing(
                input_usd_per_million=args.input_usd_per_million,
                output_usd_per_million=args.output_usd_per_million,
                cache_input_usd_per_million=args.cache_input_usd_per_million,
            ),
            request_timeout_seconds=args.request_timeout_seconds,
        ),
    )
    server = ModelGatewayHTTPServer((args.listen_host, args.listen_port), gateway)
    bound_host, bound_port = server.server_address[:2]
    base_url = args.advertise_base_url or f"http://{bound_host}:{bound_port}/v1"
    usage_url = base_url.rstrip("/")
    if usage_url.endswith("/v1"):
        usage_url = usage_url[:-3]
    usage_url += "/__autobench/usage"
    ready = {
        "status": "READY",
        "model": args.model,
        "model_route": "shared_budget_gateway",
        "base_url": base_url,
        "usage_url": usage_url,
        "listen_host": bound_host,
        "listen_port": bound_port,
        "streaming_qualified": False,
    }
    text = json.dumps(ready, sort_keys=True)
    if args.ready_file:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.ready_file.with_suffix(args.ready_file.suffix + ".tmp")
        temporary.write_text(text + "\n", encoding="utf-8")
        temporary.replace(args.ready_file)
    print(text, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
