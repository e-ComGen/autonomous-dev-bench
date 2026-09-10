"""Paid-only DeepSeek-V4 exact budget proxy entrypoint.

Unlike ``model_proxy_cli`` this command never accepts fixture estimate maps. It
loads the immutable qualified DeepSeek-V4 encoder/tokenizer from an already
populated local cache, refuses network fallback, and keeps the upstream provider
credential inside the proxy process. Benchmark arms receive only the client key.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
from threading import Thread

from .deepseek_v4_estimator import (
    DEEPSEEK_V4_MODEL,
    DEEPSEEK_V4_REPO_ID,
    DEEPSEEK_V4_REVISION,
    DeepSeekV4RequestEstimator,
)
from .experiment_manifest import BudgetManifest
from .model_budget import ModelBudgetGateway
from .model_proxy import BudgetedModelProxyCore
from .model_proxy_http import BudgetProxyHttpConfig, BudgetProxyHttpServer


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required environment variable {name}")
    return value


def _budget(path: Path) -> BudgetManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("budget JSON must be an object")
    return BudgetManifest(**raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AUTOBENCH paid exact DeepSeek-V4 budget proxy")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default=DEEPSEEK_V4_MODEL)
    parser.add_argument("--upstream-chat-url", default="https://api.deepseek.com/chat/completions")
    parser.add_argument("--upstream-key-env", default="AUTOBENCH_UPSTREAM_API_KEY")
    parser.add_argument("--client-key-env", default="AUTOBENCH_PROXY_CLIENT_API_KEY")
    parser.add_argument("--budget-json", type=Path, required=True)
    parser.add_argument("--estimator-cache-dir", type=Path, required=True)
    parser.add_argument("--ready-json", type=Path)
    parser.add_argument("--final-usage-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise ValueError("paid proxy port must be between 1 and 65535")
    if args.model != DEEPSEEK_V4_MODEL:
        raise ValueError("paid proxy model differs from the qualified DeepSeek-V4 route")
    cache = args.estimator_cache_dir.resolve()
    if not cache.is_dir():
        raise ValueError("pinned estimator cache directory is missing")

    estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
        expected_model=args.model,
        repo_id=DEEPSEEK_V4_REPO_ID,
        revision=DEEPSEEK_V4_REVISION,
        cache_dir=cache,
        allow_network=False,
    )
    gateway = ModelBudgetGateway(_budget(args.budget_json))
    core = BudgetedModelProxyCore(gateway, estimator, expected_model=args.model)
    server = BudgetProxyHttpServer(
        (args.listen_host, args.port),
        core,
        BudgetProxyHttpConfig(
            upstream_chat_completions_url=args.upstream_chat_url,
            upstream_api_key=_required_env(args.upstream_key_env),
            client_api_key=_required_env(args.client_key_env),
        ),
    )

    ready = {
        "schema_version": 1,
        "mode": "paid_exact_deepseek_v4",
        "listen_host": args.listen_host,
        "port": args.port,
        "model": args.model,
        "estimator": {
            "repo_id": estimator.identity.repo_id,
            "revision": estimator.identity.revision,
            "encoding_file": estimator.identity.encoding_file,
        },
        "real_upstream_credential_exposed_to_client": False,
        "heuristic_token_counting": False,
    }
    text = json.dumps(ready, sort_keys=True)
    print(text, flush=True)
    if args.ready_json is not None:
        args.ready_json.parent.mkdir(parents=True, exist_ok=True)
        args.ready_json.write_text(text + "\n", encoding="utf-8")

    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        Thread(target=server.shutdown, daemon=True).start()

    for name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, name, None)
        if value is not None:
            signal.signal(value, stop)

    exit_code = 0
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        snapshot = core.snapshot()
        final_usage = {
            "schema_version": 1,
            "accounting_unknown": snapshot.accounting_unknown,
            "unknown_request_sha256": list(snapshot.unknown_request_sha256),
            "budget": asdict(snapshot.budget),
        }
        if args.final_usage_json is not None:
            args.final_usage_json.parent.mkdir(parents=True, exist_ok=True)
            args.final_usage_json.write_text(json.dumps(final_usage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            core.require_clean_accounting()
        except Exception as error:
            print(f"paid proxy accounting invalid: {type(error).__name__}: {error}", flush=True)
            exit_code = 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
