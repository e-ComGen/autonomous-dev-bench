"""TEST ONLY: deterministic HTTP fixture; never used by production ab execution."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def do_POST(self):
        if self.path != "/fixture/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length < 1048576:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(length))
        model = data["model"]
        record = Path(getattr(self.server, "request_path", "/results/request.json"))
        record.write_text(json.dumps({"model": model, "stream": data.get("stream"),
            "message_count": len(data["messages"]), "tools": data.get("tools", [])}), encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if data.get("stream") else "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        usage = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
        if data.get("stream"):
            header = {"id": "fixture-only", "object": "chat.completion.chunk", "created": 1, "model": model}
            chunks = [dict(header, choices=[{"index": 0, "delta": {"role": "assistant", "content": "native-transport-ok"}, "finish_reason": None}]),
                      dict(header, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}], usage=usage)]
            for chunk in chunks:
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({"id": "fixture-only", "object": "chat.completion", "created": 1, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "native-transport-ok"}, "finish_reason": "stop"}],
                "usage": usage}).encode())
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8787), Handler).serve_forever()
