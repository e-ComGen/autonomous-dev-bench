import json

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayPricing,
    SharedModelGateway,
    parse_openai_sse_usage,
    parse_openai_usage,
)


class FakeResponse:
    def __init__(self, payload, *, status=200, content_type="application/json"):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def budget(**overrides):
    values = dict(
        input_token_cap=1000,
        output_token_cap=500,
        total_model_token_cap=1200,
        max_requests=10,
        wall_time_seconds=60,
        patch_byte_cap=1000,
    )
    values.update(overrides)
    return BudgetManifest(**values)


def gateway(response, *, ledger=None, content_type="application/json"):
    captured = []

    def opener(request, timeout):
        captured.append((request, timeout))
        return FakeResponse(response, content_type=content_type)

    config = ModelGatewayConfig(
        client_token="trial-token",
        upstream_base_url="https://provider.example/v1",
        upstream_api_key="upstream-secret",
        expected_model="deepseek-v4-flash",
        pricing=ModelGatewayPricing(
            input_usd_per_million=2.0,
            output_usd_per_million=4.0,
            cache_input_usd_per_million=0.5,
        ),
    )
    return SharedModelGateway(ledger or ModelBudgetGateway(budget()), config, opener=opener), captured


def request_body(**overrides):
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "fix it"}],
        "max_tokens": 100,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def sse_body(*, prompt=5, completion=3, cache=1, reasoning=2, done=True, include_usage=True):
    events = [
        b'data: {"choices":[{"delta":{"role":"assistant","content":"ok"}}]}\n\n',
    ]
    if include_usage:
        usage = {
            "choices": [],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "prompt_tokens_details": {"cached_tokens": cache},
                "completion_tokens_details": {"reasoning_tokens": reasoning},
            },
        }
        events.append(("data: " + json.dumps(usage, separators=(",", ":")) + "\n\n").encode())
    if done:
        events.append(b"data: [DONE]\n\n")
    return b"".join(events)


def test_parse_usage_supports_cached_and_reasoning_token_details():
    usage = parse_openai_usage(
        {
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 12,
                "prompt_tokens_details": {"cached_tokens": 10},
                "completion_tokens_details": {"reasoning_tokens": 4},
            }
        }
    )
    assert (usage.input_tokens, usage.output_tokens) == (30, 12)
    assert usage.cache_tokens == 10
    assert usage.reasoning_tokens == 4


def test_parse_sse_usage_requires_terminal_usage_and_done():
    usage = parse_openai_sse_usage(sse_body())
    assert (usage.input_tokens, usage.output_tokens) == (5, 3)
    assert usage.cache_tokens == 1
    assert usage.reasoning_tokens == 2

    for invalid in (sse_body(done=False), sse_body(include_usage=False)):
        try:
            parse_openai_sse_usage(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid SSE accounting was accepted")


def test_successful_proxy_settles_authoritative_usage_and_never_forwards_client_token():
    proxy, captured = gateway(
        {
            "id": "response",
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 10,
            },
        }
    )

    status, body, _ = proxy.proxy_json("/v1/chat/completions", request_body())

    assert status == 200
    assert json.loads(body)["id"] == "response"
    snapshot = proxy.snapshot_payload()
    assert snapshot["requests"] == 1
    assert snapshot["input_tokens"] == 30
    assert snapshot["output_tokens"] == 20
    assert snapshot["total_model_tokens"] == 50
    assert snapshot["cache_tokens"] == 10
    assert snapshot["cost_usd_micros"] == 125
    request, timeout = captured[0]
    assert request.full_url == "https://provider.example/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer upstream-secret"
    assert "trial-token" not in repr(request.header_items())
    assert timeout == 120


def test_buffered_sse_is_returned_byte_for_byte_and_settled_from_terminal_usage():
    original = sse_body(prompt=13, completion=5, cache=4, reasoning=1)
    proxy, captured = gateway(original, content_type="text/event-stream")

    status, body, content_type = proxy.proxy_json(
        "/v1/chat/completions",
        request_body(stream=True, stream_options={"include_usage": True}, max_tokens=20),
    )

    assert status == 200
    assert content_type == "text/event-stream"
    assert body == original
    snapshot = proxy.snapshot_payload()
    assert snapshot["requests"] == 1
    assert snapshot["input_tokens"] == 13
    assert snapshot["output_tokens"] == 5
    assert snapshot["total_model_tokens"] == 18
    assert snapshot["cache_tokens"] == 4
    assert snapshot["reasoning_tokens"] == 1
    request, _ = captured[0]
    assert request.get_header("Accept") == "text/event-stream"


def test_stream_without_usage_request_and_model_drift_fail_before_upstream():
    proxy, captured = gateway(sse_body(), content_type="text/event-stream")

    status, _, _ = proxy.proxy_json("/v1/chat/completions", request_body(stream=True))
    assert status == 400
    status, _, _ = proxy.proxy_json("/v1/chat/completions", request_body(model="other-model"))
    assert status == 400
    assert proxy.snapshot_payload()["requests"] == 0
    assert captured == []


def test_sse_missing_terminal_usage_invalidates_accounting_fail_closed():
    proxy, _ = gateway(sse_body(include_usage=False), content_type="text/event-stream")

    status, body, _ = proxy.proxy_json(
        "/v1/chat/completions",
        request_body(stream=True, stream_options={"include_usage": True}, max_tokens=5),
    )

    assert status == 502
    assert "usage accounting invalid" in json.loads(body)["error"]
    assert proxy.snapshot_payload()["accounting_valid"] is False


def test_provider_response_without_usage_invalidates_accounting_fail_closed():
    proxy, _ = gateway({"id": "missing-usage"})

    status, body, _ = proxy.proxy_json("/v1/chat/completions", request_body())

    assert status == 502
    assert "usage accounting invalid" in json.loads(body)["error"]
    snapshot = proxy.snapshot_payload()
    assert snapshot["requests"] == 1
    assert snapshot["accounting_valid"] is False


def test_provider_overshoot_is_recorded_and_response_preserved_but_future_calls_block():
    ledger = ModelBudgetGateway(budget(total_model_token_cap=40, output_token_cap=40))
    proxy, _ = gateway(
        {"id": "overshoot", "usage": {"prompt_tokens": 30, "completion_tokens": 20}},
        ledger=ledger,
    )

    status, body, _ = proxy.proxy_json("/v1/chat/completions", request_body(max_tokens=20))
    assert status == 200
    assert json.loads(body)["id"] == "overshoot"
    snapshot = proxy.snapshot_payload()
    assert snapshot["total_model_tokens"] == 50
    assert "total_model_token_cap" in snapshot["violations"]

    status, body, _ = proxy.proxy_json("/v1/chat/completions", request_body(max_tokens=1))
    assert status == 429
    assert json.loads(body)["error"] == "model_budget_exceeded"
