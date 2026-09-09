"""Minimal OpenAI-compatible HTTP boundary backed by ``BudgetedModelProxyCore``.

Only chat-completions POSTs and a read-only usage snapshot are exposed. The real
provider credential remains controller-side; benchmark arms receive only the
proxy credential and proxy base URL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from time import monotonic
from typing import Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .model_proxy import BudgetedModelProxyCore, ExactTokenEstimateUnavailable
from .model_budget import BudgetExceeded


_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


@dataclass(frozen=True, slots=True)
class BudgetProxyHttpConfig:
    upstream_chat_completions_url: str
    upstream_api_key: str
    client_api_key: str
    upstream_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name in ("upstream_chat_completions_url", "upstream_api_key", "client_api_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.upstream_timeout_seconds <= 0:
            raise ValueError("upstream_timeout_seconds must be positive")


class BudgetProxyHttpServer(ThreadingHTTPServer):
    """Threading server carrying immutable transport configuration and shared core."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        core: BudgetedModelProxyCore,
        config: BudgetProxyHttpConfig,
    ) -> None:
        self.core = core
        self.proxy_config = config
        super().__init__(server_address, BudgetProxyRequestHandler)


class BudgetProxyRequestHandler(BaseHTTPRequestHandler):
    server: BudgetProxyHttpServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/usage":
            self._json_error(404, "not_found")
            return
        snapshot = self.server.core.snapshot()
        self._json_response(200, asdict(snapshot))

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json_error(404, "not_found")
            return
        if self.headers.get("Authorization") != f"Bearer {self.server.proxy_config.client_api_key}":
            self._json_error(401, "proxy_auth_failed")
            return

        body = self._read_request_body()
        if body is None:
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_error(400, "invalid_json")
            return
        if not isinstance(payload, dict):
            self._json_error(400, "request_must_be_object")
            return

        try:
            admission = self.server.core.admit(payload)
        except ExactTokenEstimateUnavailable as error:
            self._json_error(409, "exact_token_estimate_unavailable", str(error))
            return
        except BudgetExceeded as error:
            self._json_error(429, "model_budget_exceeded", str(error))
            return
        except (TypeError, ValueError) as error:
            self._json_error(400, "invalid_model_request", str(error))
            return

        started = monotonic()
        upstream_request = Request(
            self.server.proxy_config.upstream_chat_completions_url,
            data=body,
            method="POST",
            headers=self._upstream_headers(),
        )
        try:
            response = urlopen(upstream_request, timeout=self.server.proxy_config.upstream_timeout_seconds)
        except HTTPError as error:
            # The request reached an HTTP upstream. Without exact terminal usage,
            # conservatively invalidate accounting rather than refunding it.
            self.server.core.mark_accounting_unknown(admission)
            self._relay_http_error(error)
            return
        except Exception as error:  # transport state after dispatch attempt is uncertain
            self.server.core.mark_accounting_unknown(admission)
            self._json_error(502, "upstream_transport_unknown", type(error).__name__)
            return

        usage: Mapping[str, object] | None = None
        client_open = True
        self.send_response(response.status)
        for name, value in response.headers.items():
            if name.lower() not in _HOP_BY_HOP:
                self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        try:
            while True:
                line = response.readline()
                if not line:
                    break
                if client_open:
                    try:
                        self.wfile.write(line)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # Continue draining the provider stream so accounting can
                        # still reach its terminal usage chunk.
                        client_open = False
                parsed = self._sse_usage(line)
                if parsed is not None:
                    usage = parsed
        finally:
            response.close()

        if usage is None:
            self.server.core.mark_accounting_unknown(admission)
            return
        try:
            self.server.core.commit_usage(
                admission,
                usage,
                wall_time_ms=max(0, int((monotonic() - started) * 1000)),
            )
        except Exception:
            self.server.core.mark_accounting_unknown(admission)
            raise

    def _read_request_body(self) -> bytes | None:
        value = self.headers.get("Content-Length")
        if value is None:
            self._json_error(411, "content_length_required")
            return None
        try:
            length = int(value)
        except ValueError:
            self._json_error(400, "invalid_content_length")
            return None
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._json_error(413, "request_too_large")
            return None
        return self.rfile.read(length)

    def _upstream_headers(self) -> dict[str, str]:
        forwarded: dict[str, str] = {}
        for name, value in self.headers.items():
            lower = name.lower()
            if lower in _HOP_BY_HOP or lower == "authorization":
                continue
            forwarded[name] = value
        forwarded["Authorization"] = f"Bearer {self.server.proxy_config.upstream_api_key}"
        forwarded["Content-Type"] = self.headers.get("Content-Type", "application/json")
        return forwarded

    @staticmethod
    def _sse_usage(line: bytes) -> Mapping[str, object] | None:
        stripped = line.strip()
        if not stripped.startswith(b"data:"):
            return None
        data = stripped[5:].strip()
        if not data or data == b"[DONE]":
            return None
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        usage = payload.get("usage")
        return usage if isinstance(usage, Mapping) else None

    def _relay_http_error(self, error: HTTPError) -> None:
        body = error.read()
        self.send_response(error.code)
        content_type = error.headers.get("Content-Type") if error.headers is not None else None
        self.send_header("Content-Type", content_type or "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _json_error(self, status: int, code: str, detail: str | None = None) -> None:
        payload: dict[str, object] = {"error": {"code": code}}
        if detail is not None:
            payload["error"]["message"] = detail  # type: ignore[index]
        self._json_response(status, payload)

    def _json_response(self, status: int, payload: object) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True
