"""A narrowly routed credential relay outside both agent containers.

The agent network is Docker-internal. Only this sidecar has external connectivity.
No arbitrary URL proxy, no retry, no API key in worker environments or receipts.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError
import json
import os
import sys

from ledger import Ledger, AdmissionDenied


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise URLError("Provider redirect refused")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"READY")

    def do_POST(self):
        token = self.path.strip("/").split("/")[0]
        sequence = None
        usage = None
        status = "UNKNOWN"
        try:
            if self.path != f"/{token}/chat/completions":
                raise AdmissionDenied("UNSUPPORTED_ROUTE")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= self.server.config["request_bytes"]:
                raise AdmissionDenied("REQUEST_SIZE_LIMIT")
            self.connection.settimeout(30)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise AdmissionDenied("INCOMPLETE_REQUEST")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise AdmissionDenied("INVALID_REQUEST")
            sequence = self.server.ledger.admit(token, body)
            request = Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                              headers={"Authorization": "Bearer " + self.server.api_key,
                                       "Content-Type": "application/json", "Accept-Encoding": "identity"})
            with build_opener(NoRedirect()).open(request, timeout=120) as upstream:
                self.send_response(upstream.status)
                self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
                self.send_header("Connection", "close")
                self.end_headers()
                consumed = 0
                if body.get("stream"):
                    for line in upstream:
                        consumed += len(line)
                        if consumed > 16777216:
                            raise AdmissionDenied("RESPONSE_SIZE_LIMIT")
                        if line.startswith(b"data: ") and line.strip() != b"data: [DONE]":
                            chunk = json.loads(line[6:])
                            if isinstance(chunk.get("usage"), dict):
                                usage = chunk["usage"]
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    response = upstream.read(16777217)
                    if len(response) > 16777216:
                        raise AdmissionDenied("RESPONSE_SIZE_LIMIT")
                    usage = json.loads(response).get("usage")
                    self.wfile.write(response)
                status = "RETURNED"
        except (AdmissionDenied, ValueError) as error:
            status = "DENIED"
            if sequence is None:
                self.send_error(429, str(error)[:80])
        except HTTPError as error:
            status = f"HTTP_{error.code}"
            self.send_error(error.code, "Provider request failed")
            error.close()
        except (OSError, URLError, TimeoutError):
            status = "EFFECT_STATUS_UNKNOWN" if sequence is not None else "TRANSPORT_ERROR"
        finally:
            self.close_connection = True
            if sequence is not None:
                self.server.ledger.complete(token, sequence, usage, status)


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    key = os.environ.pop("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is required in the relay only")
    server = ThreadingHTTPServer(("0.0.0.0", 8787), Handler)
    server.config, server.api_key = config, key
    server.ledger = Ledger(config, "/results/provider.json")
    server.serve_forever()


if __name__ == "__main__":
    main()
