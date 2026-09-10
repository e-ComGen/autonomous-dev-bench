from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from tools.capture_deepseek_v4_live_usage import MODEL, capture, parity_request, reusable_capture


class _Provider(BaseHTTPRequestHandler):
    seen_authorization = None
    seen_request = None

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        type(self).seen_authorization = self.headers.get("authorization")
        type(self).seen_request = json.loads(self.rfile.read(length).decode("utf-8"))
        payloads = [
            {"choices": [{"delta": {"reasoning_content": ""}, "finish_reason": None}]},
            {
                "choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 17,
                    "completion_tokens": 2,
                    "total_tokens": 19,
                    "prompt_cache_hit_tokens": 3,
                    "completion_tokens_details": {"reasoning_tokens": 1},
                },
            },
        ]
        body = "".join("data: " + json.dumps(p) + "\n\n" for p in payloads) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded)))
        self.send_header("x-request-id", "provider-request-1")
        self.end_headers()
        self.wfile.write(encoded)


def _server(handler=_Provider):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_parity_request_matches_pinned_harness_wire_shape() -> None:
    request = parity_request(text="Reply with OK.", max_tokens=8)
    assert request["model"] == MODEL
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["thinking"] == {"type": "enabled"}
    assert request["reasoning_effort"] == "high"
    assert request["max_tokens"] == 8


def test_capture_preserves_request_and_terminal_usage_without_recording_credential() -> None:
    server, thread = _server()
    token = "fixture-token"
    try:
        request = parity_request(text="Reply with OK.", max_tokens=8)
        result = capture(
            request,
            api_key=token,
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_seconds=5,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert _Provider.seen_authorization == "Bearer " + token
    assert _Provider.seen_request == request
    assert result["request"] == request
    assert result["usage"]["prompt_tokens"] == 17
    assert result["usage"]["total_tokens"] == 19
    assert result["provider_request_id"] == "provider-request-1"
    assert result["credential_recorded"] is False
    assert token not in json.dumps(result)


def test_reusable_capture_requires_exact_provider_model_and_wire_request(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    request = parity_request(text="Reply with OK.", max_tokens=8)
    evidence = {
        "schema_version": 1,
        "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_CAPTURE",
        "request": request,
        "usage": {"prompt_tokens": 37, "completion_tokens": 1, "total_tokens": 38},
        "model_called": True,
        "provider": "deepseek-official",
        "model": MODEL,
        "provider_request_id": "real-request-id",
        "credential_recorded": False,
    }
    path.write_text(json.dumps(evidence), encoding="utf-8")

    assert reusable_capture(path, request) == evidence

    changed = parity_request(text="different", max_tokens=8)
    assert reusable_capture(path, changed) is None
    evidence["provider"] = "other-provider"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert reusable_capture(path, request) is None


def test_reusable_capture_rejects_verifier_or_malformed_evidence(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    request = parity_request(text="Reply with OK.", max_tokens=8)
    path.write_text(
        json.dumps(
            {
                "scope": "PHASE3B_DEEPSEEK_V4_LIVE_PROVIDER_PROMPT_USAGE_PARITY",
                "request": request,
                "usage": {"prompt_tokens": 37},
                "model_called": True,
                "provider": "deepseek-official",
                "model": MODEL,
                "credential_recorded": False,
            }
        ),
        encoding="utf-8",
    )
    assert reusable_capture(path, request) is None

    path.write_text("not-json", encoding="utf-8")
    assert reusable_capture(path, request) is None


def test_capture_fails_when_terminal_usage_is_missing() -> None:
    class NoUsage(_Provider):
        def do_POST(self):
            body = 'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            encoded = body.encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server, thread = _server(NoUsage)
    try:
        with pytest.raises(RuntimeError, match="without terminal usage"):
            capture(
                parity_request(text="x", max_tokens=1),
                api_key="fixture-token",
                base_url=f"http://127.0.0.1:{server.server_port}",
                timeout_seconds=5,
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_request_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        parity_request(text="", max_tokens=8)
    with pytest.raises(ValueError):
        parity_request(text="x", max_tokens=0)
