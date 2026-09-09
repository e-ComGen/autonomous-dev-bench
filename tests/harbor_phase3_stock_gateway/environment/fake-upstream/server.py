#!/usr/bin/env python3
"""Deterministic SSE upstream for StockDeepSeekAgent shared-gateway qualification."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

PROMPT_TOKENS = 3
COMPLETION_TOKENS = 3
EXPECTED_FILE = "/workspace/stock-harness.txt"
EXPECTED_CONTENT = "created by stock deepseek harness\n"
EXPECTED_KEY = os.environ.get("FAKE_UPSTREAM_API_KEY", "")


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.tool_call_requests = 0
        self.tool_result_requests = 0
        self.auxiliary_requests = 0
        self.bad_auth = 0
        self.models: set[str] = set()

    def record(self, body: dict[str, object], *, kind: str) -> None:
        with self.lock:
            self.requests += 1
            self.tool_call_requests += int(kind == "tool_call")
            self.tool_result_requests += int(kind == "tool_result")
            self.auxiliary_requests += int(kind == "auxiliary")
            model = body.get("model")
            if isinstance(model, str):
                self.models.add(model)

    def auth_failure(self) -> None:
        with self.lock:
            self.bad_auth += 1

    def payload(self) -> dict[str, object]:
        with self.lock:
            return {
                "requests": self.requests,
                "tool_call_requests": self.tool_call_requests,
                "tool_result_requests": self.tool_result_requests,
                "auxiliary_requests": self.auxiliary_requests,
                "bad_auth": self.bad_auth,
                "prompt_tokens": self.requests * PROMPT_TOKENS,
                "completion_tokens": self.requests * COMPLETION_TOKENS,
                "models": sorted(self.models),
            }


STATE = State()


def message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def advertised_tool_names(body: dict[str, object]) -> set[str]:
    tools = body.get("tools")
    if not isinstance(tools, list):
        return set()
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
    return names


def user_text(messages: list[object]) -> str:
    return "\n".join(
        message_text(message.get("content"))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    )


def text_chunks(text: str) -> list[dict[str, object]]:
    return [
        {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
        {"choices": [{"delta": {"content": text}}]},
        {
            "choices": [{"delta": {"content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": COMPLETION_TOKENS},
        },
    ]


def tool_call_chunks() -> list[dict[str, object]]:
    arguments = {"file_path": EXPECTED_FILE, "content": EXPECTED_CONTENT}
    return [
        {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "stock-write-file",
                        "type": "function",
                        "function": {"name": "write", "arguments": json.dumps(arguments)},
                    }]
                }
            }]
        },
        {
            "choices": [{"delta": {"content": ""}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": COMPLETION_TOKENS},
        },
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stats":
            body = json.dumps(STATE.payload(), sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not EXPECTED_KEY or self.headers.get("authorization") != f"Bearer {EXPECTED_KEY}":
            STATE.auth_failure()
            self.send_error(401, "bad upstream credential")
            return
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        if body.get("stream") is not True:
            self.send_error(400, "stock qualification requires streaming")
            return
        stream_options = body.get("stream_options")
        if not isinstance(stream_options, dict) or stream_options.get("include_usage") is not True:
            self.send_error(400, "stock qualification requires streaming usage")
            return
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self.send_error(400, "missing messages")
            return
        latest = next(
            (message for message in reversed(messages) if isinstance(message, dict) and message.get("role") != "system"),
            None,
        )
        if latest is None:
            self.send_error(400, "missing non-system message")
            return

        names = advertised_tool_names(body)
        task_visible = "stock-harness.txt" in user_text(messages)
        if latest.get("role") == "tool" and task_visible:
            content = message_text(latest.get("content"))
            if "Created file" not in content or EXPECTED_FILE not in content:
                self.send_error(400, "unexpected write tool result")
                return
            chunks = text_chunks("STOCK_SHARED_GATEWAY_OK")
            STATE.record(body, kind="tool_result")
        elif task_visible and "write" in names:
            chunks = tool_call_chunks()
            STATE.record(body, kind="tool_call")
        else:
            chunks = text_chunks("phase3-stock-auxiliary")
            STATE.record(body, kind="auxiliary")

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    if not EXPECTED_KEY:
        raise SystemExit("FAKE_UPSTREAM_API_KEY is required")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
