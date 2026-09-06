"""Evaluator-owned executable probes for the public HTTPX development workload."""
from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from benchmark_core.result import SystemObservation
from suites.auto_refactoring import RefactoringLabels, RefactoringOracleContext


_PROBE = r'''
import asyncio, inspect, json
import httpx
from httpx import DEFAULT_TRANSPORT_PROVIDERS, TransportProviderRegistry
from httpx._transports.base import AsyncBaseTransport, BaseTransport
counts = {"sync_created": 0, "sync_closed": 0, "async_created": 0, "async_closed": 0}
class SyncTransport(BaseTransport):
    def __init__(self, **kwargs): counts["sync_created"] += 1
    def handle_request(self, request): return httpx.Response(200, request=request)
    def close(self): counts["sync_closed"] += 1
class AsyncTransport(AsyncBaseTransport):
    def __init__(self, **kwargs): counts["async_created"] += 1
    async def handle_async_request(self, request): return httpx.Response(200, request=request)
    async def aclose(self): counts["async_closed"] += 1
registry = DEFAULT_TRANSPORT_PROVIDERS.with_provider("counted", sync_factory=SyncTransport, async_factory=AsyncTransport)
immutable_registry = False
try: registry.sync_factories["mutate"] = SyncTransport
except TypeError: immutable_registry = True
client = httpx.Client(transport_provider="counted", transport_provider_registry=registry, trust_env=False)
response = client.get("https://example.invalid/"); client.close()
async def use_async():
    client = httpx.AsyncClient(transport_provider="counted", transport_provider_registry=registry, trust_env=False)
    response = await client.get("https://example.invalid/"); await client.aclose(); return response.status_code
async_status = asyncio.run(use_async())
unknown_error = False
try: httpx.Client(transport_provider="missing", transport_provider_registry=registry, trust_env=False)
except ValueError as exc: unknown_error = "unknown transport provider" in str(exc)
injected = httpx.MockTransport(lambda request: httpx.Response(204, request=request))
injected_client = httpx.Client(transport=injected, trust_env=False)
injected_status = injected_client.get("https://example.invalid/").status_code
injected_preserved = injected_client._transport is injected
injected_client.close()
mutual_exclusion = False
try: httpx.Client(transport=injected, transport_provider="counted", transport_provider_registry=registry, trust_env=False)
except ValueError: mutual_exclusion = True
sync_signature = inspect.signature(httpx.Client); async_signature = inspect.signature(httpx.AsyncClient)
sync_params = list(sync_signature.parameters); async_params = list(async_signature.parameters)
def additive_signature_ok(signature, names):
    params = signature.parameters
    return all(params[name].kind is inspect.Parameter.KEYWORD_ONLY for name in ("transport_provider", "transport_provider_registry")) and names.index("transport_provider") == names.index("transport") + 1 and names.index("transport_provider_registry") == names.index("transport_provider") + 1 and params["transport_provider"].default is None and params["transport_provider_registry"].default is DEFAULT_TRANSPORT_PROVIDERS
print(json.dumps({
  "sync_factory_exactly_once": counts["sync_created"] == 1 and counts["sync_closed"] == 1 and response.status_code == 200,
  "async_factory_exactly_once": counts["async_created"] == 1 and counts["async_closed"] == 1 and async_status == 200,
  "unknown_key_error": unknown_error, "injected_transport_preserved": injected_preserved and injected_status == 204,
  "mutual_exclusion": mutual_exclusion, "immutable_registry": immutable_registry,
  "public_api_additive": additive_signature_ok(sync_signature, sync_params) and additive_signature_ok(async_signature, async_params) and TransportProviderRegistry is not None,
  "public_exports": sorted(httpx.__all__),
  "counts": counts,
}))
'''


def run_httpx_feature_probes(workspace: Path, *, python_executable: str | None = None,
                             timeout_seconds: float = 60) -> dict[str, object]:
    environment = {name: os.environ[name] for name in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TMP", "TEMP") if name in os.environ}
    environment.update({"PYTHONPATH": str(workspace), "PYTHONHASHSEED": "0"})
    completed = subprocess.run(
        (python_executable or sys.executable, "-c", _PROBE), cwd=workspace, env=environment,
        text=True, capture_output=True, timeout=timeout_seconds, check=False, shell=False,
    )
    if completed.returncode != 0:
        return {"probe_execution": False, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"probe_execution": False, "error": str(exc), "stdout": completed.stdout, "stderr": completed.stderr}
    result["probe_execution"] = True
    return result


def _baseline_public_exports(workspace: Path) -> tuple[str, ...]:
    completed = subprocess.run(("git", "-C", str(workspace), "show", "HEAD:httpx/__init__.py"), text=True, capture_output=True, check=True)
    tree = ast.parse(completed.stdout)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            value = ast.literal_eval(node.value)
            return tuple(sorted(value))
    raise ValueError("pinned HTTPX baseline has no literal __all__")


def _duplicate_dispatch_present(workspace: Path) -> bool:
    tree = ast.parse((workspace / "httpx/_client.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "create" and any(keyword.arg == "async_mode" and isinstance(keyword.value, ast.Constant)
             and keyword.value.value is False for keyword in node.keywords)]
    return len(calls) > 1


@dataclass(frozen=True)
class HttpxRefactoringOracleContextFactory:
    """Resolve the task's oracle reference through real public client behavior."""

    python_executable: str | None = None
    oracle_id = "private:httpx/transport_provider"
    oracle_version = "2"
    labels_ref = "private:auto_refactoring/labels/v1"

    def __call__(self, workspace: Path, observation: SystemObservation) -> RefactoringOracleContext:
        probes = run_httpx_feature_probes(workspace, python_executable=self.python_executable)
        required = ("sync_factory_exactly_once", "async_factory_exactly_once", "unknown_key_error", "injected_transport_preserved", "mutual_exclusion", "immutable_registry")
        functional = bool(probes.get("probe_execution")) and all(probes.get(name) is True for name in required)
        expected_exports = tuple(sorted((*_baseline_public_exports(workspace), "DEFAULT_TRANSPORT_PROVIDERS", "TransportProviderRegistry")))
        public_api = probes.get("public_api_additive") is True and tuple(probes.get("public_exports", ())) == expected_exports
        mutation_present = _duplicate_dispatch_present(workspace)
        return RefactoringOracleContext(
            labels=RefactoringLabels(True, True, ("factory", "strategy", "existing_transport_abstraction")),
            functional_preserved=functional, differential_preserved=functional and probes.get("injected_transport_preserved") is True,
            public_api_preserved=public_api, mutation_presence_verified=mutation_present,
            design_opportunity_verified=mutation_present and not functional,
            mutation_evidence={"ast_duplicate_dispatch": mutation_present},
            design_evidence={"httpx_feature_probes": probes},
        )
