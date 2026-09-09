"""Paid Phase 3D ADCP receipt semantics.

Product-readiness keeps its older strict CANDIDATE_READY-only receipt. A real
benchmark arm must instead distinguish a legitimate bounded agent outcome from an
infrastructure failure: BLOCKED/BUDGET_EXHAUSTED/FAILED_BOUNDED are valid terminal
arm results and are graded as an empty patch because ADCP did not hand a candidate
out for external integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .adcp_contract import (
    ADCP_MODEL_ROUTE,
    ADCP_PROVIDER_ROUTE,
    ADCPRuntimeTarget,
    ROLE_NAMES,
)


PHASE3D_ADCP_RECEIPT_SCHEMA = "autobench.phase3d-adcp-harbor-result/1"
TERMINAL_OUTCOMES = frozenset(
    {
        "CANDIDATE_READY",
        "BLOCKED_DEPENDENCY",
        "BLOCKED_ARCHITECTURE",
        "BLOCKED_REQUIREMENT",
        "BUDGET_EXHAUSTED",
        "CANCELLED",
        "FENCED",
        "FAILED_BOUNDED",
    }
)


class Phase3DADCPReceiptError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Phase3DADCPRunnerReceipt:
    target_runtime: ADCPRuntimeTarget
    runtime_loaded: bool
    role_ids: Mapping[str, str]
    role_call_counts: Mapping[str, int]
    event_sequence: tuple[str, ...]
    outcome_status: str
    reason_code: str
    candidate_ready: bool
    task_completed: bool
    model_route: str
    provider_route: str
    model_calls_via_budget_proxy: bool
    upstream_provider_credential_present: bool
    proxy_credential_present: bool
    model_called: bool
    session_id: str
    request_id: str
    candidate_snapshot_id: str | None
    repair_count: int
    scope_projection_id: str

    @property
    def exports_candidate(self) -> bool:
        return self.outcome_status == "CANDIDATE_READY"


_FIELDS = {
    "schema", "target_runtime", "runtime_loaded", "role_ids", "role_call_counts",
    "event_sequence", "outcome_status", "reason_code", "candidate_ready", "task_completed",
    "model_route", "provider_route", "model_calls_via_budget_proxy",
    "upstream_provider_credential_present", "proxy_credential_present", "model_called",
    "session_id", "request_id", "candidate_snapshot_id", "repair_count",
    "scope_projection_id",
}


def parse_phase3d_adcp_runner_receipt(raw: Mapping[str, object]) -> Phase3DADCPRunnerReceipt:
    if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
        missing = sorted(_FIELDS - set(raw)) if isinstance(raw, Mapping) else sorted(_FIELDS)
        extra = sorted(set(raw) - _FIELDS) if isinstance(raw, Mapping) else []
        raise Phase3DADCPReceiptError(f"paid ADCP receipt fields mismatch; missing={missing}, extra={extra}")
    if raw.get("schema") != PHASE3D_ADCP_RECEIPT_SCHEMA:
        raise Phase3DADCPReceiptError("unknown paid ADCP receipt schema")

    target_raw = _mapping(raw.get("target_runtime"), "target_runtime")
    if set(target_raw) != {"repository", "commit", "runtime", "integration"}:
        raise Phase3DADCPReceiptError("target_runtime fields mismatch")
    target = ADCPRuntimeTarget(
        _text(target_raw.get("repository"), "target repository"),
        _text(target_raw.get("commit"), "target commit"),
        _text(target_raw.get("runtime"), "target runtime"),
        _text(target_raw.get("integration"), "target integration"),
    )
    if target != ADCPRuntimeTarget.expected():
        raise Phase3DADCPReceiptError("paid runner targets a different ADCP production identity")
    if not _boolean(raw.get("runtime_loaded"), "runtime_loaded"):
        raise Phase3DADCPReceiptError("paid ADCP runner must load the exact private runtime")

    ids_raw = _mapping(raw.get("role_ids"), "role_ids")
    counts_raw = _mapping(raw.get("role_call_counts"), "role_call_counts")
    if set(ids_raw) != set(ROLE_NAMES) or set(counts_raw) != set(ROLE_NAMES):
        raise Phase3DADCPReceiptError("receipt must bind exactly architect/coder/reviewer/verifier")
    role_ids = {name: _text(ids_raw[name], f"{name} role id") for name in ROLE_NAMES}
    if len(set(role_ids.values())) != len(ROLE_NAMES):
        raise Phase3DADCPReceiptError("ADCP role identities must remain distinct")
    role_counts = {name: _non_negative(counts_raw[name], f"{name} role call count") for name in ROLE_NAMES}

    sequence_raw = raw.get("event_sequence")
    if not isinstance(sequence_raw, list) or any(not isinstance(item, str) or not item for item in sequence_raw):
        raise Phase3DADCPReceiptError("event_sequence must be a string list")
    event_sequence = tuple(sequence_raw)
    allowed_events = {"ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "RESEARCHER", "HANDS"}
    if any(item not in allowed_events for item in event_sequence):
        raise Phase3DADCPReceiptError("event_sequence contains an unknown role")

    outcome = _text(raw.get("outcome_status"), "outcome_status")
    if outcome not in TERMINAL_OUTCOMES:
        raise Phase3DADCPReceiptError("unknown ADCP terminal outcome")
    ready = _boolean(raw.get("candidate_ready"), "candidate_ready")
    if ready != (outcome == "CANDIDATE_READY"):
        raise Phase3DADCPReceiptError("candidate_ready must exactly match CANDIDATE_READY outcome")
    if _boolean(raw.get("task_completed"), "task_completed"):
        raise Phase3DADCPReceiptError("ZoneDevelopmentRuntime may not claim TASK_COMPLETED")
    if ready:
        _require_subsequence(event_sequence, ("ARCHITECT", "CODER", "REVIEWER", "VERIFIER"))

    model_route = _text(raw.get("model_route"), "model_route")
    provider_route = _text(raw.get("provider_route"), "provider_route")
    if model_route != ADCP_MODEL_ROUTE or provider_route != ADCP_PROVIDER_ROUTE:
        raise Phase3DADCPReceiptError("paid ADCP arm changed model/provider identity")
    if not _boolean(raw.get("model_calls_via_budget_proxy"), "model_calls_via_budget_proxy"):
        raise Phase3DADCPReceiptError("paid ADCP model calls must use the shared budget proxy")
    if _boolean(raw.get("upstream_provider_credential_present"), "upstream_provider_credential_present"):
        raise Phase3DADCPReceiptError("paid ADCP runner must not possess upstream provider credentials")
    if not _boolean(raw.get("proxy_credential_present"), "proxy_credential_present"):
        raise Phase3DADCPReceiptError("paid ADCP runner requires the proxy credential")

    candidate_raw = raw.get("candidate_snapshot_id")
    candidate = None if candidate_raw is None else _text(candidate_raw, "candidate_snapshot_id")
    if ready and candidate is None:
        raise Phase3DADCPReceiptError("CANDIDATE_READY requires a concrete candidate_snapshot_id")

    return Phase3DADCPRunnerReceipt(
        target_runtime=target,
        runtime_loaded=True,
        role_ids=role_ids,
        role_call_counts=role_counts,
        event_sequence=event_sequence,
        outcome_status=outcome,
        reason_code=_text(raw.get("reason_code"), "reason_code"),
        candidate_ready=ready,
        task_completed=False,
        model_route=model_route,
        provider_route=provider_route,
        model_calls_via_budget_proxy=True,
        upstream_provider_credential_present=False,
        proxy_credential_present=True,
        model_called=_boolean(raw.get("model_called"), "model_called"),
        session_id=_text(raw.get("session_id"), "session_id"),
        request_id=_text(raw.get("request_id"), "request_id"),
        candidate_snapshot_id=candidate,
        repair_count=_non_negative(raw.get("repair_count"), "repair_count"),
        scope_projection_id=_sha256_id(raw.get("scope_projection_id"), "scope_projection_id"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise Phase3DADCPReceiptError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Phase3DADCPReceiptError(f"{name} must be non-empty text")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise Phase3DADCPReceiptError(f"{name} must be boolean")
    return value


def _non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Phase3DADCPReceiptError(f"{name} must be a non-negative integer")
    return value


def _sha256_id(value: object, name: str) -> str:
    text = _text(value, name)
    if not text.startswith("sha256:") or len(text) != 71:
        raise Phase3DADCPReceiptError(f"{name} must be a sha256 identity")
    try:
        int(text[7:], 16)
    except ValueError as error:
        raise Phase3DADCPReceiptError(f"{name} must be hexadecimal") from error
    return text.lower()


def _require_subsequence(sequence: tuple[str, ...], required: tuple[str, ...]) -> None:
    cursor = 0
    for item in sequence:
        if cursor < len(required) and item == required[cursor]:
            cursor += 1
    if cursor != len(required):
        raise Phase3DADCPReceiptError(f"event_sequence lacks required ordered subsequence {required}")
