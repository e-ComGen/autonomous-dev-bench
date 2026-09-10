from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ADCP_REPOSITORY = "e-ComGen/autonomous-dev-control-plane"
ADCP_COMMIT = "e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
ADCP_RUNTIME = "packages.zone_development.ZoneDevelopmentRuntime"
ADCP_RUNTIME_CLASS = "packages.zone_development.projection_runtime.ZoneDevelopmentRuntime"
ADCP_INTEGRATION = "existing-v2-runtime-role-ports"


def git(path: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()


def qualify(adcp_path: Path) -> dict[str, object]:
    adcp_path = adcp_path.resolve()
    if not adcp_path.is_dir():
        raise ValueError(f"ADCP checkout missing: {adcp_path}")
    head = git(adcp_path, "rev-parse", "HEAD")
    if head != ADCP_COMMIT:
        raise ValueError(f"ADCP checkout mismatch: expected {ADCP_COMMIT}, got {head}")
    if git(adcp_path, "status", "--porcelain"):
        raise ValueError("ADCP checkout must be clean")

    sys.path.insert(0, str(adcp_path / "packages" / "shared_contracts" / "src"))
    sys.path.insert(0, str(adcp_path))

    from examples.zone_development.fixture import ExternalZone
    from tests.harness_bridge.support import gateway, zone_handler
    from packages.zone_development import ZoneDevelopmentRuntime
    from packages.zone_development.contracts import DevelopmentOutcome, OutcomeStatus, Role

    runtime_class = f"{ZoneDevelopmentRuntime.__module__}.{ZoneDevelopmentRuntime.__qualname__}"
    if runtime_class != ADCP_RUNTIME_CLASS:
        raise ValueError(f"runtime class mismatch: {runtime_class}")

    with tempfile.TemporaryDirectory(prefix="autobench-phase3c2-") as temp:
        root = Path(temp)
        zone = ExternalZone(root / "zone")
        bridge, protocol = gateway(root / "exchange.sqlite3", zone_handler(zone))
        runtime = ZoneDevelopmentRuntime.from_harness(
            bridge,
            zone.journal,
            architect_id=zone.roles.architect.identity.actor_id,
            coder_id=zone.roles.coder.identity.actor_id,
            reviewer_id=zone.roles.reviewer.identity.actor_id,
            verifier_id=zone.roles.verifier.identity.actor_id,
        )
        if type(runtime) is not ZoneDevelopmentRuntime:
            raise ValueError("from_harness bypassed the public qualified runtime")

        outcome = runtime.develop(zone.request, zone.worktree)
        if not isinstance(outcome, DevelopmentOutcome) or outcome.status is not OutcomeStatus.CANDIDATE_READY:
            raise ValueError(f"expected CANDIDATE_READY, got {outcome!r}")
        if outcome.candidate is None:
            raise ValueError("CANDIDATE_READY is missing candidate")

        calls = list(protocol.calls)
        sequence = [call.role.value for call in calls]
        roles = {Role.ARCHITECT.value, Role.CODER.value, Role.REVIEWER.value, Role.VERIFIER.value}
        if not roles <= set(sequence):
            raise ValueError(f"required Harness roles missing: {sequence}")
        counts = {role: sequence.count(role) for role in sorted(roles)}
        if counts[Role.CODER.value] < 2 or counts[Role.REVIEWER.value] < 2 or counts[Role.VERIFIER.value] < 2:
            raise ValueError("bounded repair/review/verify cycle was not exercised")

        actors: dict[str, str] = {}
        for call in calls:
            if call.role.value in roles:
                previous = actors.setdefault(call.role.value, call.actor_id)
                if previous != call.actor_id:
                    raise ValueError("role identity changed during session")
        if len(set(actors.values())) != 4:
            raise ValueError("Architect/Coder/Reviewer/Verifier identities are not distinct")

        diff = git(zone.worktree, "diff", "--no-ext-diff", "--binary")
        paths = [p for p in git(zone.worktree, "diff", "--name-only").splitlines() if p]
        if paths != ["zone_a/pricing.py"] or not diff.strip():
            raise ValueError(f"unexpected private runtime write set: {paths}")

        return {
            "schema_version": 1,
            "scope": "PHASE3C2_PINNED_PRIVATE_ADCP_RUNTIME_TEST_HARNESS_FIXTURE",
            "status": "PASS",
            "target": {
                "repository": ADCP_REPOSITORY,
                "commit": head,
                "runtime": ADCP_RUNTIME,
                "runtime_class": runtime_class,
                "integration": ADCP_INTEGRATION,
            },
            "private_runtime_loaded": True,
            "assured_runtime_loaded": True,
            "harness_bridge_loaded": True,
            "harness_binding": "fixture-only.not-the-external-kit/1",
            "canonical_external_harness_protocol_claimed": False,
            "model_called": False,
            "paid_model_called": False,
            "upstream_provider_credential_used": False,
            "candidate_ready": True,
            "task_completed": False,
            "publication_performed": False,
            "integration_performed": False,
            "repair_count": outcome.session.repairs,
            "role_actor_ids": actors,
            "role_call_counts": counts,
            "event_role_sequence": sequence,
            "changed_paths": paths,
            "patch_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "patch_bytes": len(diff.encode()),
            "candidate_snapshot_id": outcome.candidate.candidate_snapshot_id.value,
            "session_id": outcome.session.session_id,
            "request_id": outcome.request_id,
            "production_ready": False,
            "production_blocker": "PINNED_PRIVATE_ADCP_REAL_PROTOCOL_BINDING_NOT_QUALIFIED",
        }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--adcp-path", required=True, type=Path)
    p.add_argument("--evidence", required=True, type=Path)
    args = p.parse_args()
    result = qualify(args.adcp_path)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
