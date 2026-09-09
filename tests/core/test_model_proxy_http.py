from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_proxy import BudgetedModelProxyCore, PinnedRequestEstimator, RequestBudgetEstimate
from benchmark_core.model_proxy_http import BudgetProxyHttpConfig, BudgetProxyHttpServer


MODEL = "deepseek-v4-flash"
CLIENT_KEY = "proxy-only-key"
UPSTREAM_KEY = "real-provider-key"


def _budget() -> BudgetManifest:
    return BudgetManifest(
        input_token_cap=100,
        output_token_cap=100,
        total_model_token_cap=180,
        max_requests=3,
        wall_time_seconds=60,
        patch_byte_cap=1000,
    )


def _request() -> dict[str, object]:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 40,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


class _FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, include_usage: bool = True):
        self.requests: list[dict[str, object]] = []
        self.authorizations: list[str | None] = []
        self.include_usage = include_usage
        super().__init__(("127.0.0.1", 0), _FakeUpstreamHandler)


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    server: _FakeUpstream

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.server.requests.append(payload)
        self.server.authorizations.append(self.headers.get("Authorization"))

        chunks: list[dict[str, object]] = [
            {
                "choices": [
                    {"delta": {"content": "ok"}, "finish_reason": None}
                ]
            },
            {
                "choices": [
                    {"delta": {}, "finish_reason": "stop"}
                ]
            },
        ]
        if self.server.include_usage:
            chunks.append(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                        "prompt_cache_hit_tokens": 2,
                        "completion_tokens_details": {"reasoning_tokens": 4},
                    },
                }
            )

        body = b"".join(
            b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
            for chunk in chunks
        ) + b"data: [DONE]\n\n"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(server: ThreadingHTTPServer) -> Thread:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _proxy(upstream: _FakeUpstream, request: dict[str, object], *, known: bool = True) -> BudgetProxyHttpServer:
    estimates = {}
    if known:
        estimates[PinnedRequestEstimator.request_sha256(request)] = RequestBudgetEstimate(20, 40, 60)
    core = BudgetedModelProxyCore(
        ModelBudgetGateway(_budget()),
        PinnedRequestEstimator(estimates),
        expected_model=MODEL,
    )
    upstream_url = f"http://127.0.0.1:{upstream.server_address[1]}/chat/completions"
    return BudgetProxyHttpServer(
        ("127.0.0.1", 0),
        core,
        BudgetProxyHttpConfig(
            upstream_chat_completions_url=upstream_url,
            upstream_api_key=UPSTREAM_KEY,
            client_api_key=CLIENT_KEY,
        ),
    )


def _post(proxy: BudgetProxyHttpServer, request: dict[str, object], *, key: str = CLIENT_KEY) -> bytes:
    body = json.dumps(request, separators=(",", ":")).encode()
    http_request = Request(
        f"http://127.0.0.1:{proxy.server_address[1]}/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(http_request, timeout=5) as response:
        return response.read()


def test_proxy_hides_real_credential_streams_response_and_commits_usage() -> None:
    request = _request()
    upstream = _FakeUpstream()
    proxy = _proxy(upstream, request)
    _serve(upstream)
    _serve(proxy)
    try:
        body = _post(proxy, request)
        assert b"data: [DONE]" in body
        assert upstream.requests == [request]
        assert upstream.authorizations == [f"Bearer {UPSTREAM_KEY}"]

        snapshot = proxy.core.snapshot()
        assert not snapshot.accounting_unknown
        assert snapshot.budget.requests == 1
        assert snapshot.budget.input_tokens == 20
        assert snapshot.budget.output_tokens == 10
        assert snapshot.budget.total_model_tokens == 30
        assert snapshot.budget.cache_tokens == 2
        assert snapshot.budget.reasoning_tokens == 4
        proxy.core.require_clean_accounting()

        with urlopen(f"http://127.0.0.1:{proxy.server_address[1]}/usage", timeout=5) as response:
            usage = json.loads(response.read())
        assert usage["accounting_unknown"] is False
        assert usage["budget"]["requests"] == 1
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_unknown_exact_estimate_rejects_before_upstream_dispatch() -> None:
    request = _request()
    upstream = _FakeUpstream()
    proxy = _proxy(upstream, request, known=False)
    _serve(upstream)
    _serve(proxy)
    try:
        with pytest.raises(HTTPError) as caught:
            _post(proxy, request)
        assert caught.value.code == 409
        assert upstream.requests == []
        assert proxy.core.gateway.snapshot().requests == 0
        assert proxy.core.gateway.snapshot().open_reservations == 0
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_wrong_proxy_credential_never_reaches_upstream() -> None:
    request = _request()
    upstream = _FakeUpstream()
    proxy = _proxy(upstream, request)
    _serve(upstream)
    _serve(proxy)
    try:
        with pytest.raises(HTTPError) as caught:
            _post(proxy, request, key="wrong")
        assert caught.value.code == 401
        assert upstream.requests == []
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_missing_terminal_usage_is_accounting_unknown_and_reservation_is_not_refunded() -> None:
    request = _request()
    upstream = _FakeUpstream(include_usage=False)
    proxy = _proxy(upstream, request)
    _serve(upstream)
    _serve(proxy)
    try:
        body = _post(proxy, request)
        assert b"data: [DONE]" in body

        snapshot = proxy.core.snapshot()
        assert snapshot.accounting_unknown
        assert snapshot.budget.requests == 0
        assert snapshot.budget.open_reservations == 1
        assert snapshot.budget.reserved_total_tokens == 60
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()
