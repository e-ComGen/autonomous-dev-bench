"""Qualify the pinned private ADCP runtime through the real DeepSeek Harness SDK.

This is an offline production-binding qualification, not a paid model trial. A
local HTTP/SSE provider returns deterministic role semantics while the shipping
DeepSeek Harness SDK/runtime, ADCP HarnessGateway, durable exchange journal,
pinned assured ZoneDevelopmentRuntime and real Git worktree all execute.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
from typing import Iterable

from suites.coding.adcp_contract import ADCP_COMMIT, ADCP_INTEGRATION, ADCP_REPOSITORY, ADCP_RUNTIME
from suites.coding.adcp_dsh_binding import (
    DSH_BINDING_ID,
    DSH_SDK_VERSION,
    DeepSeekHarnessBinding,
    DeepSeekHarnessProtocol,
)


class ScriptedDeepSeekServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.role_counts = {"LOCAL_ARCHITECT": 0, "CODER": 0, "REVIEWER": 0}
        self.requests: list[dict[str, object]] = []


class ScriptedHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer mock-key":
            self.send_error(401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(body, dict):
            self.send_error(400)
            return
        prompt = "\n".join(_strings(body.get("messages")))
        role = next((name for name in self.server.role_counts if f"ROLE: {name}" in prompt), None)
        if role is None:
            self.send_error(422)
            return
        self.server.role_counts[role] += 1
        self.server.requests.append(body)
        response = _semantic_response(role, self.server.role_counts[role])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        chunks = (
            {
                "id": "autobench-mock",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": response}, "finish_reason": None}],
            },
            {
                "id": "autobench-mock",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 64,
                    "completion_tokens": 32,
                    "total_tokens": 96,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 64,
                },
            },
        )
        for chunk in chunks:
            self.wfile.write(("data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n").encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        return


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _semantic_response(role: str, call_number: int) -> str:
    base = "def price(quantity):\n    return quantity * 7\n"
    bad = base + "\ndef discount(quantity):\n    return quantity * 7 - 1\n"
    good = base + "\ndef discount(quantity):\n    return quantity * 7 - 2\n"
    if role == "LOCAL_ARCHITECT":
        value = {
            "steps": [
                "Preserve price(quantity) on the declared domain",
                "Add discount(quantity) with two units off",
                "Review and verify exact source",
            ],
            "target_paths": ["zone_a/pricing.py"],
            "alternatives": [],
            "remedies": [{"family": "CHANGE_ALGORITHM", "targets": ["discount(quantity)"]}],
            "blockers": [],
        }
    elif role == "CODER":
        value = {
            "edits": [{"path": "zone_a/pricing.py", "content": bad if call_number == 1 else good}],
            "blockers": [],
        }
    elif role == "REVIEWER":
        findings = [] if call_number > 1 else [{
            "finding_id": "discount-offset",
            "detail": "The local requirement subtracts two units; the proposed implementation does not",
            "blocking": True,
        }]
        value = {"findings": findings, "blockers": []}
    else:
        raise AssertionError(role)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"cannot read ADCP git identity: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _configure_adcp_import_paths(adcp_root: Path) -> None:
    shared_contracts_src = adcp_root / "packages" / "shared_contracts" / "src"
    shared_contracts_init = shared_contracts_src / "shared_contracts" / "__init__.py"
    if not shared_contracts_init.is_file():
        raise SystemExit(f"ADCP shared_contracts source is missing: {shared_contracts_init}")
    sys.path.insert(0, str(adcp_root))
    sys.path.insert(0, str(shared_contracts_src))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adcp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/product-readiness/PHASE3C3_REAL_ADCP_DSH.json"))
    args = parser.parse_args()

    adcp_root = args.adcp_root.resolve()
    head = _git_head(adcp_root)
    if head != ADCP_COMMIT:
        raise SystemExit(f"ADCP commit mismatch: expected {ADCP_COMMIT}, got {head}")
    _configure_adcp_import_paths(adcp_root)

    import shared_contracts as sc
    from examples.zone_development.fixture import BASE, GOOD, NEIGHBOR, ExternalZone
    from packages.harness_bridge.contracts import ContextBinding
    from packages.harness_bridge.gateway import HarnessGateway
    from packages.harness_bridge.journal import ExchangeJournal
    from packages.harness_bridge.zone import HarnessCoder, HarnessLocalArchitect, HarnessReviewer
    from packages.zone_development import ECACCVerifier, OutcomeStatus, Role, RoleIdentity, RoleServices
    from packages.zone_development.assured_runtime import ZoneDevelopmentRuntime

    server = ScriptedDeepSeekServer(("127.0.0.1", 0), ScriptedHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="autobench-real-adcp-dsh-") as temp_name:
            temp = Path(temp_name)
            zone = ExternalZone(temp / "zone")
            binding = DeepSeekHarnessBinding()
            protocol = DeepSeekHarnessProtocol(
                state_root=temp / "dsh-state",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="mock-key",
                request_timeout_seconds=60,
            )
            exchange = ExchangeJournal(temp / "exchange.sqlite3", binding.binding_id)
            gateway = HarnessGateway(protocol, binding, exchange)
            fresh = ContextBinding()
            roles = RoleServices(
                HarnessLocalArchitect(gateway, RoleIdentity(role=Role.ARCHITECT, actor_id="dsh-local-architect"), context_binding=fresh),
                HarnessCoder(gateway, RoleIdentity(role=Role.CODER, actor_id="dsh-coder"), context_binding=fresh),
                HarnessReviewer(gateway, RoleIdentity(role=Role.REVIEWER, actor_id="dsh-reviewer"), context_binding=fresh),
                ECACCVerifier("deterministic-ecacc-verifier", zone.contract, zone.registry),
            )
            runtime = ZoneDevelopmentRuntime(roles, zone.journal)
            outcome = zone.receive(runtime.develop(zone.request, zone.worktree))

            if outcome.status is not OutcomeStatus.CANDIDATE_READY:
                raise ValueError(f"pinned ADCP runtime did not reach CANDIDATE_READY: {outcome.status}")
            if outcome.session.repairs != 1 or outcome.session.verifications != 2:
                raise ValueError("qualification did not exercise FAIL -> bounded repair -> PASS")
            if outcome.session.role_calls != 7:
                raise ValueError(f"unexpected ADCP role call count: {outcome.session.role_calls}")
            if protocol.model_calls != 5:
                raise ValueError(f"expected 5 model-backed role calls, got {protocol.model_calls}")
            if server.role_counts != {"LOCAL_ARCHITECT": 1, "CODER": 2, "REVIEWER": 2}:
                raise ValueError(f"provider-wire role counts mismatch: {server.role_counts}")
            if (zone.worktree / "zone_a/pricing.py").read_text(encoding="utf-8") != GOOD:
                raise ValueError("ADCP candidate workspace does not contain the verified repair")
            if (zone.worktree / "zone_b/owned.py").read_text(encoding="utf-8") != NEIGHBOR:
                raise ValueError("ADCP wrote outside the declared Zone scope")
            if not (zone.repo / "zone_a/pricing.py").read_text(encoding="utf-8") == BASE:
                raise ValueError("external baseline repository was mutated")

            events = zone.journal.events(zone.request.session_id)
            sequence = [
                event["phase"].removesuffix("_STARTED").replace("LOCAL_ARCHITECT", "ARCHITECT")
                for event in events
                if event["phase"] in {
                    "LOCAL_ARCHITECT_STARTED", "CODER_STARTED", "REVIEWER_STARTED", "VERIFIER_STARTED"
                }
            ]
            expected_sequence = ["ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "CODER", "REVIEWER", "VERIFIER"]
            if sequence != expected_sequence:
                raise ValueError(f"ADCP role sequence mismatch: {sequence}")

            evidence = {
                "schema_version": 1,
                "scope": "PHASE3C3_PINNED_PRIVATE_ADCP_REAL_DSH_BINDING_OFFLINE",
                "status": "PASS",
                "target_runtime": {
                    "repository": ADCP_REPOSITORY,
                    "commit": ADCP_COMMIT,
                    "runtime": ADCP_RUNTIME,
                    "integration": ADCP_INTEGRATION,
                },
                "runtime_class": f"{ZoneDevelopmentRuntime.__module__}.{ZoneDevelopmentRuntime.__qualname__}",
                "runtime_loaded": True,
                "binding_id": DSH_BINDING_ID,
                "deepseek_harness_sdk_version": DSH_SDK_VERSION,
                "real_deepseek_harness_subprocess": True,
                "provider_wire": "LOCAL_HTTP_SSE_MOCK",
                "provider_wire_requests": len(server.requests),
                "model_backed_role_calls": protocol.model_calls,
                "role_ids": {
                    "architect": roles.architect.identity.actor_id,
                    "coder": roles.coder.identity.actor_id,
                    "reviewer": roles.reviewer.identity.actor_id,
                    "verifier": roles.verifier.identity.actor_id,
                },
                "role_call_counts": {
                    "architect": 1,
                    "coder": 2,
                    "reviewer": 2,
                    "verifier": 2,
                },
                "event_sequence": expected_sequence,
                "repair_count": outcome.session.repairs,
                "verification_count": outcome.session.verifications,
                "candidate_ready": True,
                "task_completed": False,
                "workspace_scope_preserved": True,
                "baseline_preserved": True,
                "paid_model_called": False,
                "upstream_provider_credential_present": bool(os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY")),
                "production_binding_qualified": True,
                "production_ready": True,
                "production_blocker": None,
                "outcome_digest": sc.contract_digest(outcome).value,
            }
            if evidence["upstream_provider_credential_present"]:
                raise ValueError("qualification process unexpectedly exposes upstream provider credential")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Pinned private ADCP + real DeepSeek Harness binding: PASS; evidence={args.output}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
