"""CLI process for the budgeted OpenAI-compatible model proxy.

The bundled estimator loader is intentionally fixture-only. Paid execution must
supply a production exact tokenizer-aware estimator in a later qualification
step; this command cannot silently fall back to heuristic token counting.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
from threading import Event, Thread

from .experiment_manifest import BudgetManifest
from .model_budget import ModelBudgetGateway
from .model_proxy import BudgetedModelProxyCore, PinnedRequestEstimator, RequestBudgetEstimate
from .model_proxy_http import BudgetProxyHttpConfig, BudgetProxyHttpServer


def _nonempty_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_budget(path: Path) -> BudgetManifest:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("budget JSON must be an object")
    return BudgetManifest(**payload)


def _load_fixture_estimates(path: Path) -> PinnedRequestEstimator:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("mode") != "fixture_exact_request_map":
        raise ValueError("only fixture_exact_request_map estimator files are accepted by this entrypoint")
    raw = payload.get("estimates")
    if not isinstance(raw, dict):
        raise ValueError("estimates must be an object keyed by canonical request sha256")
    estimates: dict[str, RequestBudgetEstimate] = {}
    for digest, value in raw.items():
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(value, dict):
            raise ValueError("invalid fixture estimate entry")
        estimates[digest] = RequestBudgetEstimate(**value)
    return PinnedRequestEstimator(estimates)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AUTOBENCH budgeted model proxy (fixture qualification mode)")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--model", required=True)
    parser.add_argument("--upstream-chat-url", required=True)
    parser.add_argument("--upstream-key-env", default="AUTOBENCH_UPSTREAM_API_KEY")
    parser.add_argument("--client-key-env", default="AUTOBENCH_PROXY_CLIENT_API_KEY")
    parser.add_argument("--budget-json", type=Path, required=True)
    parser.add_argument("--fixture-estimates-json", type=Path, required=True)
    parser.add_argument("--ready-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        raise ValueError("port must be between 0 and 65535")

    gateway = ModelBudgetGateway(_load_budget(args.budget_json))
    estimator = _load_fixture_estimates(args.fixture_estimates_json)
    core = BudgetedModelProxyCore(gateway, estimator, expected_model=args.model)
    server = BudgetProxyHttpServer(
        (args.listen_host, args.port),
        core,
        BudgetProxyHttpConfig(
            upstream_chat_completions_url=args.upstream_chat_url,
            upstream_api_key=_nonempty_env(args.upstream_key_env),
            client_api_key=_nonempty_env(args.client_key_env),
        ),
    )

    ready_payload = {
        "schema_version": 1,
        "mode": "fixture_qualification_only",
        "listen_host": args.listen_host,
        "port": server.server_address[1],
        "base_url": f"http://{args.listen_host}:{server.server_address[1]}/v1",
        "usage_url": f"http://{args.listen_host}:{server.server_address[1]}/usage",
        "model": args.model,
        "real_upstream_credential_exposed_to_client": False,
        "heuristic_token_counting": False,
    }
    encoded = json.dumps(ready_payload, sort_keys=True)
    print(encoded, flush=True)
    if args.ready_json is not None:
        args.ready_json.parent.mkdir(parents=True, exist_ok=True)
        args.ready_json.write_text(encoded + "\n", encoding="utf-8")

    stop = Event()

    def request_stop(*_: object) -> None:
        stop.set()
        Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signal_name, None)
        if sig is not None:
            signal.signal(sig, request_stop)

    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()

    core.require_clean_accounting()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
