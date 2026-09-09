"""Qualify the shared model gateway over real HTTP with a deterministic upstream."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


CLIENT_TOKEN = "PHASE3_HTTP_CLIENT_TOKEN_DO_NOT_PERSIST"
UPSTREAM_KEY = "PHASE3_HTTP_UPSTREAM_KEY_DO_NOT_PERSIST"
MODEL = "deepseek-v4-flash"


class FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.requests_seen: list[dict[str, object]] = []
        super().__init__(("127.0.0.1", 0), FakeUpstreamHandler)


class FakeUpstreamHandler(BaseHTTPRequestHandler):
    server: FakeUpstream

    def log_message(self, format: str, *args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        authorization = self.headers.get("Authorization")
        self.server.requests_seen.append(
            {
                "path": self.path,
                "authorization": authorization,
                "model": payload.get("model"),
                "stream": payload.get("stream"),
            }
        )
        if authorization != f"Bearer {UPSTREAM_KEY}":
            self.send_response(401)
            self.end_headers()
            return
        response = {
            "id": "phase3-fake-upstream",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        }
        body = json.dumps(response, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def request_json(url: str, payload: dict[str, object] | None, *, token: str | None) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read()
        decoded = json.loads(body.decode("utf-8")) if body else {}
        return int(error.code), decoded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/harbor-phase3/PHASE3_MODEL_GATEWAY_TRANSPORT.json"),
    )
    args = parser.parse_args()

    upstream = FakeUpstream()
    upstream_thread = Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}/v1"

    ledger = ModelBudgetGateway(
        BudgetManifest(
            input_token_cap=100,
            output_token_cap=50,
            total_model_token_cap=120,
            max_requests=4,
            wall_time_seconds=60,
            patch_byte_cap=1000,
        )
    )
    gateway = SharedModelGateway(
        ledger,
        ModelGatewayConfig(
            client_token=CLIENT_TOKEN,
            upstream_base_url=upstream_url,
            upstream_api_key=UPSTREAM_KEY,
            expected_model=MODEL,
            pricing=ModelGatewayPricing(
                input_usd_per_million=1.0,
                output_usd_per_million=2.0,
                cache_input_usd_per_million=1.0,
            ),
        ),
    )
    server = ModelGatewayHTTPServer(("127.0.0.1", 0), gateway)
    gateway_thread = Thread(target=server.serve_forever, daemon=True)
    gateway_thread.start()
    gateway_root = f"http://127.0.0.1:{server.server_port}"

    checks: dict[str, bool] = {}
    try:
        status, response = request_json(
            gateway_root + "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "transport"}],
                "max_tokens": 20,
            },
            token=CLIENT_TOKEN,
        )
        checks["completion_status_200"] = status == 200 and response.get("id") == "phase3-fake-upstream"
        checks["one_upstream_request"] = len(upstream.requests_seen) == 1
        observed = upstream.requests_seen[0]
        checks["upstream_path_normalized"] = observed.get("path") == "/v1/chat/completions"
        checks["upstream_received_only_upstream_key"] = observed.get("authorization") == f"Bearer {UPSTREAM_KEY}"
        checks["client_token_not_forwarded"] = CLIENT_TOKEN not in str(observed)

        status, usage = request_json(gateway_root + "/__autobench/usage", None, token=CLIENT_TOKEN)
        checks["usage_status_200"] = status == 200
        checks["usage_model_exact"] = usage.get("model") == MODEL and usage.get("model_route") == "shared_budget_gateway"
        checks["usage_primary_total"] = usage.get("input_tokens") == 11 and usage.get("output_tokens") == 7 and usage.get("total_model_tokens") == 18
        checks["usage_diagnostics"] = usage.get("cache_tokens") == 3 and usage.get("reasoning_tokens") == 2
        checks["usage_request_count"] = usage.get("requests") == 1
        checks["usage_cost"] = usage.get("cost_usd_micros") == 25
        checks["usage_valid"] = usage.get("accounting_valid") is True and usage.get("violations") == []

        status, _ = request_json(gateway_root + "/__autobench/usage", None, token="wrong")
        checks["usage_auth_required"] = status == 401

        status, _ = request_json(
            gateway_root + "/v1/chat/completions",
            {"model": MODEL, "messages": [], "stream": True, "max_tokens": 1},
            token=CLIENT_TOKEN,
        )
        checks["streaming_fails_closed"] = status == 400 and len(upstream.requests_seen) == 1

        status, _ = request_json(
            gateway_root + "/v1/chat/completions",
            {"model": "wrong-model", "messages": [], "max_tokens": 1},
            token=CLIENT_TOKEN,
        )
        checks["model_drift_fails_closed"] = status == 400 and len(upstream.requests_seen) == 1
    finally:
        server.shutdown()
        server.server_close()
        upstream.shutdown()
        upstream.server_close()

    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise SystemExit(f"Phase 3 shared model gateway transport failed: {failed}")

    evidence = {
        "scope": "PHASE3_SHARED_MODEL_GATEWAY_HTTP_TRANSPORT_FAKE_UPSTREAM",
        "status": "PASS",
        "paid_model_called": False,
        "deterministic_fake_upstream": True,
        "streaming_qualified": False,
        "model": MODEL,
        "checks": checks,
        "usage": gateway.snapshot_payload(),
    }
    serialized = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if CLIENT_TOKEN in serialized or UPSTREAM_KEY in serialized:
        raise SystemExit("gateway evidence leaked a qualification credential")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(f"Phase 3 shared model gateway HTTP transport: PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
