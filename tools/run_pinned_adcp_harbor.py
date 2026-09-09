"""Operator-side runner for Phase 3C2 pinned private ADCP qualification.

This file is public and contains no private ADCP source. During qualification a
trusted operator copies an exact detached private checkout into ``/opt/adcp``.
The runner imports the pinned assured runtime and its existing deterministic
Harness test support, rewires the existing ExternalZone fixture onto Harbor's
actual ``/workspace``, and emits only the public ADCP receipt schema.

No model call is made here. The only DeepSeek connection facts visible to this
process are the experiment budget-proxy URL/token supplied by ADCPHarborAgent.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


EXPECTED_REPOSITORY = "e-ComGen/autonomous-dev-control-plane"
EXPECTED_COMMIT = "285702063815280398b95ba8696566259c8b5b34"
EXPECTED_RUNTIME = "packages.zone_development.assured_runtime.ZoneDevelopmentRuntime"
EXPECTED_INTEGRATION = "existing-v2-runtime-role-ports"
RECEIPT_SCHEMA = "autobench.adcp-harbor-result/1"


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"missing required environment variable {name}")
    return value


def _assert_target_identity() -> None:
    expected = {
        "AUTOBENCH_ADCP_TARGET_REPOSITORY": EXPECTED_REPOSITORY,
        "AUTOBENCH_ADCP_TARGET_COMMIT": EXPECTED_COMMIT,
        "AUTOBENCH_ADCP_TARGET_RUNTIME": EXPECTED_RUNTIME,
        "AUTOBENCH_ADCP_TARGET_INTEGRATION": EXPECTED_INTEGRATION,
    }
    for name, value in expected.items():
        if required(name) != value:
            raise RuntimeError(f"{name} does not match the pinned Phase 3C2 identity")
    if os.environ.get("AUTOBENCH_ADCP_FAKE_RUNTIME") == "1":
        raise RuntimeError("pinned private runtime qualification cannot run in fake mode")
    if os.environ.get("AUTOBENCH_MODEL_PROXY_MODE") != "1":
        raise RuntimeError("pinned private runtime qualification requires budget-proxy mode")
    required("DEEPSEEK_BASE_URL")
    required("DEEPSEEK_API_KEY")
    if os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"):
        raise RuntimeError("private ADCP runner received a forbidden upstream provider credential")


def _load_source_identity(source_root: Path) -> dict[str, str]:
    identity_path = Path("/opt/autobench/adcp_source_identity.json")
    value = json.loads(identity_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"repository", "commit", "tree"}:
        raise RuntimeError("invalid private ADCP source identity marker")
    if value["repository"] != EXPECTED_REPOSITORY or value["commit"] != EXPECTED_COMMIT:
        raise RuntimeError("private source marker does not match the pinned ADCP identity")
    if not isinstance(value["tree"], str) or len(value["tree"]) != 40:
        raise RuntimeError("private source marker has invalid git tree id")
    if not source_root.is_dir():
        raise RuntimeError("private ADCP source root is missing")
    return value


def _install_private_import_paths(source_root: Path) -> None:
    shared_contracts = source_root / "packages" / "shared_contracts" / "src"
    if not shared_contracts.is_dir():
        raise RuntimeError("pinned private checkout is missing shared_contracts")
    sys.path.insert(0, str(source_root))
    sys.path.insert(0, str(shared_contracts))


def _load_private_harness_support(source_root: Path):
    """Load the exact pinned TEST-ONLY Harness support without a ``tests`` import collision."""
    support_path = source_root / "tests" / "harness_bridge" / "support.py"
    if not support_path.is_file():
        raise RuntimeError("pinned private checkout is missing tests/harness_bridge/support.py")
    spec = importlib.util.spec_from_file_location("autobench_pinned_adcp_harness_support", support_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned private Harness support module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_harbor_zone(workspace: Path, temporary: Path, source_root: Path):
    import shared_contracts as sc
    from examples.zone_development.fixture import BASE, GOOD, NEIGHBOR, ExternalZone, source_ref
    from packages.zone_development import SessionJournal, ZoneDevelopmentRuntime

    support = _load_private_harness_support(source_root)
    gateway = support.gateway
    runtime = support.runtime
    zone_handler = support.zone_handler

    if ZoneDevelopmentRuntime.__module__ != "packages.zone_development.assured_runtime":
        raise RuntimeError(
            f"packages.zone_development.ZoneDevelopmentRuntime is not the assured runtime: "
            f"{ZoneDevelopmentRuntime.__module__}"
        )

    pricing = workspace / "zone_a" / "pricing.py"
    neighbor = workspace / "zone_b" / "owned.py"
    if pricing.read_text(encoding="utf-8") != BASE:
        raise RuntimeError("Harbor pricing baseline differs from the pinned fixture baseline")
    if neighbor.read_text(encoding="utf-8") != NEIGHBOR:
        raise RuntimeError("Harbor neighbor baseline differs from the pinned fixture baseline")

    # Reuse the exact pinned fixture to construct evaluation contracts, immutable
    # Attempt/version vectors, role providers and verifier registry. Only the
    # external workspace binding is replaced so the real runtime writes directly
    # into Harbor's repository instead of its fixture worktree.
    zone = ExternalZone(temporary / "fixture-zone")
    repository_id = zone.request.baseline.repository_id
    zone.worktree = workspace
    zone.request = replace(
        zone.request,
        baseline=source_ref(repository_id, workspace),
        workspace_id="harbor-phase3c-private",
        workspace_generation=1,
    )
    zone.journal = SessionJournal(temporary / "development.sqlite3")

    harness_gateway, protocol = gateway(temporary / "exchange.sqlite3", zone_handler(zone))
    assured = runtime(zone, harness_gateway)
    if assured.__class__.__module__ != "packages.zone_development.assured_runtime":
        raise RuntimeError("from_harness composition bypassed the pinned assured runtime")

    outcome = assured.develop(zone.request, workspace)
    return zone, protocol, outcome, GOOD, NEIGHBOR, sc, assured.__class__.__module__


def _role_name(role_value: str) -> str:
    return {
        "LOCAL_ARCHITECT": "architect",
        "CODER": "coder",
        "REVIEWER": "reviewer",
        "VERIFIER": "verifier",
    }.get(role_value, role_value.lower())


def main() -> int:
    _assert_target_identity()
    source_root = Path("/opt/adcp").resolve()
    source_identity = _load_source_identity(source_root)
    _install_private_import_paths(source_root)

    instruction_path = Path(required("AUTOBENCH_ADCP_INSTRUCTION_PATH"))
    if not instruction_path.read_text(encoding="utf-8").strip():
        raise RuntimeError("ADCP instruction is empty")
    workspace = Path(required("AUTOBENCH_ADCP_WORKSPACE")).resolve()
    result_path = Path(required("AUTOBENCH_ADCP_RESULT_PATH"))

    from packages.harness_bridge.contracts import AgentRole
    from packages.zone_development import OutcomeStatus

    with tempfile.TemporaryDirectory(prefix="autobench-adcp-private-") as tmp:
        zone, protocol, outcome, good, neighbor, sc, runtime_module = _prepare_harbor_zone(
            workspace,
            Path(tmp),
            source_root,
        )

        if outcome.status is not OutcomeStatus.CANDIDATE_READY:
            raise RuntimeError(f"pinned assured runtime did not reach CANDIDATE_READY: {outcome}")
        if (workspace / "zone_a" / "pricing.py").read_text(encoding="utf-8") != good:
            raise RuntimeError("pinned assured runtime did not materialize the repaired candidate in Harbor workspace")
        if (workspace / "zone_b" / "owned.py").read_text(encoding="utf-8") != neighbor:
            raise RuntimeError("pinned assured runtime modified foreign Zone ownership")

        expected_roles = [
            AgentRole.LOCAL_ARCHITECT,
            AgentRole.CODER,
            AgentRole.REVIEWER,
            AgentRole.VERIFIER,
            AgentRole.CODER,
            AgentRole.REVIEWER,
            AgentRole.VERIFIER,
        ]
        observed_roles = [call.role for call in protocol.calls]
        if observed_roles != expected_roles:
            raise RuntimeError(f"unexpected pinned Harness role sequence: {observed_roles!r}")
        if len({call.call_id for call in protocol.calls}) != 7:
            raise RuntimeError("pinned Harness bridge did not issue seven distinct durable call ids")
        if len({call.actor_id for call in protocol.calls}) != 4:
            raise RuntimeError("pinned runtime did not preserve four distinct role actor identities")

        events = zone.journal.events(zone.request.session_id)
        ecacc = [event["result"] for event in events if event["phase"] == "ECACC_EVALUATED"]
        badc = [event["action"] for event in events if event["phase"] == "BADC_DECISION"]
        aa_admitted = sum(event["phase"] == "ARCHITECTURE_ADMITTED" for event in events)
        if ecacc != ["FAIL", "PASS"]:
            raise RuntimeError(f"real ECACC sequence mismatch: {ecacc!r}")
        if badc != ["REPAIR", "CANDIDATE_READY"]:
            raise RuntimeError(f"real BADC sequence mismatch: {badc!r}")
        if aa_admitted < 2:
            raise RuntimeError("real Architecture Assurance admission was not observed twice")

        role_ids: dict[str, str] = {}
        counts: Counter[str] = Counter()
        event_sequence: list[str] = []
        for call in protocol.calls:
            name = _role_name(call.role.value)
            if name in {"architect", "coder", "reviewer", "verifier"}:
                role_ids.setdefault(name, call.actor_id)
                counts[name] += 1
                event_sequence.append(name.upper())
            if len(event_sequence) == 4:
                event_sequence.append("BADC_REPAIR")
        event_sequence.append("CANDIDATE_READY")

        if set(role_ids) != {"architect", "coder", "reviewer", "verifier"}:
            raise RuntimeError(f"could not project exact four role identities: {role_ids!r}")

        candidate = outcome.candidate
        if candidate is None:
            raise RuntimeError("CANDIDATE_READY outcome has no candidate snapshot")

        receipt = {
            "schema": RECEIPT_SCHEMA,
            "target_runtime": {
                "repository": EXPECTED_REPOSITORY,
                "commit": EXPECTED_COMMIT,
                "runtime": EXPECTED_RUNTIME,
                "integration": EXPECTED_INTEGRATION,
            },
            "runtime_loaded": True,
            "fake_runtime": False,
            "role_ids": role_ids,
            "role_call_counts": {name: counts[name] for name in ("architect", "coder", "reviewer", "verifier")},
            "event_sequence": event_sequence,
            "outcome_status": outcome.status.value,
            "candidate_ready": outcome.status is OutcomeStatus.CANDIDATE_READY,
            "task_completed": False,
            "model_route": required("AUTOBENCH_ADCP_MODEL"),
            "provider_route": required("AUTOBENCH_ADCP_PROVIDER"),
            "model_calls_via_budget_proxy": True,
            "upstream_provider_credential_present": bool(os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY")),
            "proxy_credential_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "model_called": False,
            "session_id": zone.request.session_id,
            "request_id": zone.request.request_id,
            "candidate_snapshot_id": candidate.candidate_snapshot_id.value,
            "repair_count": outcome.session.repairs,
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Sanitized diagnostics only; no private source bytes leave this process.
        diagnostics = {
            "source_repository": source_identity["repository"],
            "source_commit": source_identity["commit"],
            "source_tree": source_identity["tree"],
            "runtime_module": runtime_module,
            "harness_calls": len(protocol.calls),
            "ecacc_results": ecacc,
            "badc_actions": badc,
            "architecture_admitted_events": aa_admitted,
            "request_digest": sc.contract_digest(zone.request).value,
        }
        Path("/tmp/autobench-adcp-private-diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
