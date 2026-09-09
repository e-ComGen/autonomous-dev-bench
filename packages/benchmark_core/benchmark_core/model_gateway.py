"""Authenticated OpenAI-compatible proxy backed by :mod:`model_budget`.

One gateway instance represents one experimental arm/trial budget. Agent
containers receive only a scoped client token and this gateway's URL. The
upstream provider credential remains controller-side.

Streaming is deliberately rejected in the first Phase 3 slice because reliable
usage settlement must be qualified before streaming can be admitted into a
causal budget comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model_budget import (
    ModelBudgetExceeded,
    ModelBudgetGateway,
    ModelBudgetSnapshot,
    ModelUsage,
)


@dataclass(frozen=True, slots=True)
class ModelGatewayPricing:
    input_usd_per_million: float
    output_usd_per_million: float
    cache_input_usd_per_million: float

    def __post_init__(self) -> None:
        for field in (
            "input_usd_per_million",
            "output_usd_per_million",
            "cache_input_usd_per_million",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{field} must be a non-negative number")

    def cost_usd_micros(self, *, input_tokens: int, output_tokens: int, cache_tokens: int) -> int:
        cache = min(input_tokens, cache_tokens)
        regular_input = input_tokens - cache
        usd = (
            regular_input * self.input_usd_per_million
            + cache * self.cache_input_usd_per_million
            + output_tokens * self.output_usd_per_million
        ) / 1_000_000
        return int(round(usd * 1_000_000))


@dataclass(frozen=True, slots=True)
class ModelGatewayConfig:
    client_token: str
    upstream_base_url: str
    upstream_api_key: str
    expected_model: str
    pricing: ModelGatewayPricing
    request_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        for field in ("client_token", "upstream_base_url", "upstream_api_key", "expected_model"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be non-empty")
        if not self.upstream_base_url.startswith(("http://", "https://")):
            raise ValueError("upstream_base_url must be HTTP(S)")
        if isinstance(self.request_timeout_seconds, bool) or self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class GatewayUsage:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_tokens: int


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"provider usage field {field} must be a non-negative integer")
    return value


def parse_openai_usage(payload: Mapping[str, object]) -> GatewayUsage:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        raise ValueError("provider response is missing usage accounting")

    input_tokens = raw.get("prompt_tokens", raw.get("input_tokens"))
    output_tokens = raw.get("completion_tokens", raw.get("output_tokens"))
    input_value = _non_negative_int(input_tokens, "input_tokens")
    output_value = _non_negative_int(output_tokens, "output_tokens")

    cache_candidates: list[object] = [
        raw.get("prompt_cache_hit_tokens"),
        raw.get("cache_tokens"),
    ]
    prompt_details = raw.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cache_candidates.append(prompt_details.get("cached_tokens"))
    cache_value = 0
    for candidate in cache_candidates:
        if candidate is not None:
            cache_value = _non_negative_int(candidate, "cache_tokens")
            break

    reasoning_value = 0
    completion_details = raw.get("completion_tokens_details")
    if isinstance(completion_details, dict) and completion_details.get("reasoning_tokens") is not None:
        reasoning_value = _non_negative_int(completion_details.get("reasoning_tokens"), "reasoning_tokens")
    elif raw.get("reasoning_tokens") is not None:
        reasoning_value = _non_negative_int(raw.get("reasoning_tokens"), "reasoning_tokens")

    return GatewayUsage(
        input_tokens=input_value,
        output_tokens=output_value,
        reasoning_tokens=reasoning_value,
        cache_tokens=cache_value,
    )


def _join_upstream_path(base_url: str, request_path: str) -> str:
    base = base_url.rstrip("/")
    path = request_path.split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return base + path


class SharedModelGateway:
    """Stateful request proxy and authoritative per-arm model ledger."""

    def __init__(
        self,
        ledger: ModelBudgetGateway,
        config: ModelGatewayConfig,
        *,
        opener: Callable[..., object] = urlopen,
    ):
        self.ledger = ledger
        self.config = config
        self._opener = opener

    def snapshot_payload(self) -> dict[str, object]:
        snapshot = self.ledger.snapshot()
        return self._snapshot_payload(snapshot)

    def _snapshot_payload(self, snapshot: ModelBudgetSnapshot) -> dict[str, object]:
        result = snapshot.as_dict()
        result.update(
            {
                "model": self.config.expected_model,
                "model_route": "shared_budget_gateway",
                "pricing": {
                    "input_usd_per_million": self.config.pricing.input_usd_per_million,
                    "output_usd_per_million": self.config.pricing.output_usd_per_million,
                    "cache_input_usd_per_million": self.config.pricing.cache_input_usd_per_million,
                },
            }
        )
        return result

    def proxy_json(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "application/json",
    ) -> tuple[int, bytes, str]:
        try:
            request_payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return self._error(400, f"invalid JSON request: {error}")
        if not isinstance(request_payload, dict):
            return self._error(400, "model request must be a JSON object")
        if request_payload.get("stream") is True:
            return self._error(400, "streaming is not qualified by Phase 3 shared budget gateway")
        if request_payload.get("model") != self.config.expected_model:
            return self._error(400, "model identity differs from the experiment manifest")

        requested_output = request_payload.get("max_completion_tokens", request_payload.get("max_tokens"))
        if requested_output is not None:
            try:
                requested_output = _non_negative_int(requested_output, "requested_output_tokens")
            except ValueError as error:
                return self._error(400, str(error))

        try:
            ticket = self.ledger.admit_request(requested_output)
        except ModelBudgetExceeded as error:
            return self._json_response(429, {"error": "model_budget_exceeded", "usage": error.snapshot.as_dict()})

        upstream_url = _join_upstream_path(self.config.upstream_base_url, path)
        request = Request(
            upstream_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.upstream_api_key}",
                "Content-Type": content_type or "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.config.request_timeout_seconds) as response:
                response_body = response.read()
                status = int(getattr(response, "status", 200))
                response_type = response.headers.get("Content-Type", "application/json")
        except HTTPError as error:
            self.ledger.cancel(ticket)
            return int(error.code), error.read(), error.headers.get("Content-Type", "application/json")
        except (URLError, TimeoutError, OSError) as error:
            self.ledger.cancel(ticket)
            return self._error(502, f"upstream model request failed: {error}")

        if not 200 <= status < 300:
            self.ledger.cancel(ticket)
            return status, response_body, response_type

        try:
            provider_payload = json.loads(response_body.decode("utf-8"))
            if not isinstance(provider_payload, dict):
                raise ValueError("provider response is not a JSON object")
            usage = parse_openai_usage(provider_payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self.ledger.cancel(ticket)
            self.ledger.invalidate_accounting(str(error))
            return self._error(502, f"provider usage accounting invalid: {error}")

        cost = self.config.pricing.cost_usd_micros(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_tokens=usage.cache_tokens,
        )
        try:
            self.ledger.settle(
                ticket,
                ModelUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                    cache_tokens=usage.cache_tokens,
                    cost_usd_micros=cost,
                ),
            )
        except ModelBudgetExceeded:
            # The provider has already consumed the overshooting request. Keep
            # the real response for trajectory fidelity; future admissions are
            # blocked and the authenticated usage endpoint records the violation.
            pass
        return status, response_body, response_type

    @staticmethod
    def _error(status: int, message: str) -> tuple[int, bytes, str]:
        return SharedModelGateway._json_response(status, {"error": message})

    @staticmethod
    def _json_response(status: int, payload: Mapping[str, object]) -> tuple[int, bytes, str]:
        return status, json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json"


class ModelGatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, gateway: SharedModelGateway):
        self.gateway = gateway
        super().__init__(server_address, ModelGatewayHTTPRequestHandler)


class ModelGatewayHTTPRequestHandler(BaseHTTPRequestHandler):
    server: ModelGatewayHTTPServer

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - caller owns logging
        return

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.gateway.config.client_token}"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}', "application/json")
            return
        if self.path != "/__autobench/usage":
            self._send(404, b'{"error":"not_found"}', "application/json")
            return
        body = json.dumps(self.server.gateway.snapshot_payload(), sort_keys=True).encode("utf-8")
        self._send(200, body, "application/json")

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, b'{"error":"invalid_content_length"}', "application/json")
            return
        body = self.rfile.read(length)
        status, response, content_type = self.server.gateway.proxy_json(
            self.path,
            body,
            content_type=self.headers.get("Content-Type", "application/json"),
        )
        self._send(status, response, content_type)
