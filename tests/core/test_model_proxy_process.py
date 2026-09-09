from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.request import Request, urlopen

from benchmark_core.model_proxy import PinnedRequestEstimator


MODEL = "deepseek-v4-flash"
CLIENT_KEY = "process-proxy-key"
UPSTREAM_KEY = "process-real-upstream-key"


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.authorization: str | None = None
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        self.server.authorization = self.headers.get("Authorization")
        chunks = [
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
            },
        ]
        body = b"".join(
            b"data: " + json.dumps(item, separators=(",", ":")).encode() + b"\n\n"
            for item in chunks
        ) + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_proxy_cli_is_a_real_cross_process_credential_and_budget_boundary(tmp_path: Path) -> None:
    upstream = _Server()
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()

    request_payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 40,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    digest = PinnedRequestEstimator.request_sha256(request_payload)

    budget_path = tmp_path / "budget.json"
    budget_path.write_text(
        json.dumps(
            {
                "input_token_cap": 100,
                "output_token_cap": 100,
                "total_model_token_cap": 180,
                "max_requests": 3,
                "wall_time_seconds": 60,
                "patch_byte_cap": 1000,
            }
        ),
        encoding="utf-8",
    )
    estimates_path = tmp_path / "estimates.json"
    estimates_path.write_text(
        json.dumps(
            {
                "mode": "fixture_exact_request_map",
                "estimates": {
                    digest: {
                        "input_tokens": 20,
                        "max_output_tokens": 40,
                        "max_total_tokens": 60,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["AUTOBENCH_UPSTREAM_API_KEY"] = UPSTREAM_KEY
    env["AUTOBENCH_PROXY_CLIENT_API_KEY"] = CLIENT_KEY
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "benchmark_core.model_proxy_cli",
            "--listen-host",
            "127.0.0.1",
            "--port",
            "0",
            "--model",
            MODEL,
            "--upstream-chat-url",
            f"http://127.0.0.1:{upstream.server_address[1]}/chat/completions",
            "--budget-json",
            str(budget_path),
            "--fixture-estimates-json",
            str(estimates_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        assert process.stdout is not None
        ready_line = process.stdout.readline().strip()
        ready = json.loads(ready_line)
        assert ready["mode"] == "fixture_qualification_only"
        assert ready["real_upstream_credential_exposed_to_client"] is False
        assert ready["heuristic_token_counting"] is False

        body = json.dumps(request_payload, separators=(",", ":")).encode()
        proxy_request = Request(
            ready["base_url"] + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {CLIENT_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(proxy_request, timeout=5) as response:
            streamed = response.read()
        assert b"data: [DONE]" in streamed
        assert upstream.authorization == f"Bearer {UPSTREAM_KEY}"

        with urlopen(ready["usage_url"], timeout=5) as response:
            usage = json.loads(response.read())
        assert usage["accounting_unknown"] is False
        assert usage["budget"]["requests"] == 1
        assert usage["budget"]["total_model_tokens"] == 30
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
