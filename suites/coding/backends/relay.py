"""Loopback transport for the existing provider relay; it is not OS secret isolation."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import os


class LocalRelay:
    def __init__(self, root, directory, settings, tokens):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        from suites.coding.provider.server import Handler
        from suites.coding.provider.ledger import Ledger
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise ValueError("DEEPSEEK_API_KEY_MISSING")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        config = {"tokens": tokens, "model": settings.model, "requests_per_arm": settings.requests_per_arm,
                  "output_tokens_per_request": settings.output_tokens_per_request, "request_bytes": settings.request_bytes}
        self.receipt = directory / "provider.json"
        self.server.config, self.server.api_key = config, key
        self.server.ledger = Ledger(config, self.receipt)
        self.thread = threading.Thread(target=self.server.serve_forever, name="native-model-relay", daemon=True)
        self.thread.start()

    def endpoint(self, token):
        return f"http://127.0.0.1:{self.server.server_port}/{token}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server.api_key = ""
