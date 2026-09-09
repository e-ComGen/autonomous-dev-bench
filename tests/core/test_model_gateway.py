import json

from benchmark_core.experiment_manifest import BudgetManifest
from benchmark_core.model_budget import ModelBudgetGateway
from benchmark_core.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayPricing,
    SharedModelGateway,
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


def gateway(response, *, ledger=None):
    captured = []

    def opener(request, timeout):
        captured.append((request, timeout))
        return FakeResponse(response)

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
    # (20 regular input * $2 + 10 cache * $0.5 + 20 output * $4) / 1M
    # = $0.000125 = 125 microdollars.
    assert snapshot["cost_usd_micros"] == 125
    request, timeout = captured[0]
    assert request.full_url == "https://provider.example/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer upstream-secret"
    assert "trial-token" not in repr(request.header_items())
    assert timeout == 120


def test_streaming_and_model_drift_fail_before_any_model_request():
    proxy, captured = gateway({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    status, _, _ = proxy.proxy_json("/v1/chat/completions", request_body(stream=True))
    assert status == 400
    status, _, _ = proxy.proxy_json("/v1/chat/completions", request_body(model="other-model"))
    assert status == 400
    assert proxy.snapshot_payload()["requests"] == 0
    assert captured == []


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
