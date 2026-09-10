"""Public process contracts for the benchmark's ADCP arm.

V1 remains the strict qualification receipt: it proves CANDIDATE_READY. V2 is
the paid-experiment receipt and additionally represents valid bounded task-level
failures. A non-ready ADCP outcome is an UNRESOLVED experiment result, not an
infrastructure exclusion. Neither receipt is trusted for final SWE-bench grading.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


ADCP_REPOSITORY = "e-ComGen/autonomous-dev-control-plane"
ADCP_COMMIT = "e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
ADCP_RUNTIME = "packages.zone_development.ZoneDevelopmentRuntime"
ADCP_INTEGRATION = "existing-v2-runtime-role-ports"
ADCP_RECEIPT_SCHEMA = "autobench.adcp-harbor-result/1"
ADCP_PAID_RECEIPT_SCHEMA = "autobench.adcp-harbor-result/2"
ADCP_MODEL_ROUTE = "deepseek-v4-flash"
ADCP_PROVIDER_ROUTE = "deepseek-official"
ADCP_SCOPE_POLICY = "phase3d-public-static-python-scope-v2"
ADCP_INTERNAL_EVALUATION_POLICY = "phase3d-public-handoff-canonical-binding-v2"
ROLE_NAMES = ("architect", "coder", "reviewer", "verifier")
PAID_OUTCOME_STATUSES = {
    "CANDIDATE_READY", "BLOCKED_DEPENDENCY", "BLOCKED_ARCHITECTURE",
    "BLOCKED_REQUIREMENT", "BUDGET_EXHAUSTED", "CANCELLED", "FENCED", "FAILED_BOUNDED",
}


class ADCPReceiptError(ValueError):
    """The external runner receipt does not prove the required ADCP boundary."""


@dataclass(frozen=True, slots=True)
class ADCPRuntimeTarget:
    repository: str
    commit: str
    runtime: str
    integration: str

    @classmethod
    def expected(cls) -> "ADCPRuntimeTarget":
        return cls(ADCP_REPOSITORY, ADCP_COMMIT, ADCP_RUNTIME, ADCP_INTEGRATION)


@dataclass(frozen=True, slots=True)
class ADCPRunnerReceipt:
    target_runtime: ADCPRuntimeTarget
    runtime_loaded: bool
    fake_runtime: bool
    role_ids: Mapping[str, str]
    role_call_counts: Mapping[str, int]
    event_sequence: tuple[str, ...]
    outcome_status: str
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
    candidate_snapshot_id: str
    repair_count: int


@dataclass(frozen=True, slots=True)
class ADCPPaidRunnerReceipt:
    target_runtime: ADCPRuntimeTarget
    runtime_loaded: bool
    role_ids: Mapping[str, str]
    role_call_counts: Mapping[str, int]
    event_sequence: tuple[str, ...]
    outcome_status: str
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
    scope_policy: str
    scope_digest: str
    write_scope_paths: tuple[str, ...]
    internal_evaluation_policy: str


_V1_FIELDS = {
    "schema", "target_runtime", "runtime_loaded", "fake_runtime", "role_ids", "role_call_counts",
    "event_sequence", "outcome_status", "candidate_ready", "task_completed", "model_route",
    "provider_route", "model_calls_via_budget_proxy", "upstream_provider_credential_present",
    "proxy_credential_present", "model_called", "session_id", "request_id",
    "candidate_snapshot_id", "repair_count",
}
_V2_FIELDS = _V1_FIELDS | {
    "scope_policy", "scope_digest", "write_scope_paths", "internal_evaluation_policy",
}


def _target(raw: Mapping[str, object]) -> ADCPRuntimeTarget:
    target_raw = _mapping(raw.get("target_runtime"), "target_runtime")
    if set(target_raw) != {"repository", "commit", "runtime", "integration"}:
        raise ADCPReceiptError("target_runtime fields mismatch")
    target = ADCPRuntimeTarget(
        _text(target_raw.get("repository"), "target repository"),
        _text(target_raw.get("commit"), "target commit"),
        _text(target_raw.get("runtime"), "target runtime"),
        _text(target_raw.get("integration"), "target integration"),
    )
    if target != ADCPRuntimeTarget.expected():
        raise ADCPReceiptError("external runner targets a different ADCP production identity")
    return target


def _roles(raw: Mapping[str, object], *, allow_zero: bool) -> tuple[dict[str, str], dict[str, int]]:
    role_ids_raw = _mapping(raw.get("role_ids"), "role_ids")
    role_counts_raw = _mapping(raw.get("role_call_counts"), "role_call_counts")
    if set(role_ids_raw) != set(ROLE_NAMES) or set(role_counts_raw) != set(ROLE_NAMES):
        raise ADCPReceiptError("receipt must bind exactly architect/coder/reviewer/verifier")
    role_ids = {name: _text(role_ids_raw[name], f"{name} role id") for name in ROLE_NAMES}
    if len(set(role_ids.values())) != len(ROLE_NAMES):
        raise ADCPReceiptError("Architect, Coder, Reviewer and Verifier identities must be distinct")
    counter = _non_negative_int if allow_zero else _positive_int
    role_counts = {name: counter(role_counts_raw[name], f"{name} role call count") for name in ROLE_NAMES}
    return role_ids, role_counts


def parse_adcp_runner_receipt(
    raw: Mapping[str, object], *, allow_fake_runtime: bool = False, require_repair_cycle: bool = False,
) -> ADCPRunnerReceipt:
    """Validate the qualification CANDIDATE_READY receipt."""
    if set(raw) != _V1_FIELDS:
        _field_error(raw, _V1_FIELDS)
    if raw.get("schema") != ADCP_RECEIPT_SCHEMA:
        raise ADCPReceiptError("unknown ADCP runner receipt schema")
    target = _target(raw)
    runtime_loaded = _boolean(raw.get("runtime_loaded"), "runtime_loaded")
    fake_runtime = _boolean(raw.get("fake_runtime"), "fake_runtime")
    if fake_runtime:
        if not allow_fake_runtime:
            raise ADCPReceiptError("fake ADCP runtime is forbidden in production mode")
        if runtime_loaded:
            raise ADCPReceiptError("fake qualification cannot claim the private runtime was loaded")
    elif not runtime_loaded:
        raise ADCPReceiptError("production ADCP receipt must prove the pinned runtime was loaded")

    role_ids, role_counts = _roles(raw, allow_zero=False)
    sequence_raw = raw.get("event_sequence")
    if not isinstance(sequence_raw, list) or not sequence_raw:
        raise ADCPReceiptError("event_sequence must be a non-empty list")
    event_sequence = tuple(_text(item, "event") for item in sequence_raw)
    _require_subsequence(event_sequence, ("ARCHITECT", "CODER", "REVIEWER", "VERIFIER"))
    repair_count = _non_negative_int(raw.get("repair_count"), "repair_count")
    if require_repair_cycle:
        if repair_count < 1:
            raise ADCPReceiptError("fake qualification must exercise a bounded repair cycle")
        _require_subsequence(event_sequence, ("ARCHITECT", "CODER", "REVIEWER", "VERIFIER", "CODER", "REVIEWER", "VERIFIER"))
        if role_counts["coder"] < 2 or role_counts["reviewer"] < 2 or role_counts["verifier"] < 2:
            raise ADCPReceiptError("repair qualification requires repeated coder/reviewer/verifier calls")

    outcome_status = _text(raw.get("outcome_status"), "outcome_status")
    candidate_ready = _boolean(raw.get("candidate_ready"), "candidate_ready")
    task_completed = _boolean(raw.get("task_completed"), "task_completed")
    if outcome_status != "CANDIDATE_READY" or not candidate_ready or task_completed:
        raise ADCPReceiptError("ADCP boundary requires CANDIDATE_READY and forbids TASK_COMPLETED")
    model_route, provider_route = _model_boundary(raw)
    model_called = _boolean(raw.get("model_called"), "model_called")
    if fake_runtime and model_called:
        raise ADCPReceiptError("deterministic fake qualification must not call a model")
    return ADCPRunnerReceipt(
        target, runtime_loaded, fake_runtime, role_ids, role_counts, event_sequence,
        outcome_status, candidate_ready, task_completed, model_route, provider_route,
        True, False, True, model_called, _text(raw.get("session_id"), "session_id"),
        _text(raw.get("request_id"), "request_id"),
        _text(raw.get("candidate_snapshot_id"), "candidate_snapshot_id"), repair_count,
    )


def parse_adcp_paid_runner_receipt(raw: Mapping[str, object]) -> ADCPPaidRunnerReceipt:
    """Validate paid production output without converting task failure to infrastructure failure."""
    if set(raw) != _V2_FIELDS:
        _field_error(raw, _V2_FIELDS)
    if raw.get("schema") != ADCP_PAID_RECEIPT_SCHEMA:
        raise ADCPReceiptError("unknown paid ADCP runner receipt schema")
    target = _target(raw)
    if _boolean(raw.get("fake_runtime"), "fake_runtime"):
        raise ADCPReceiptError("fake ADCP runtime is forbidden in paid experiment mode")
    if not _boolean(raw.get("runtime_loaded"), "runtime_loaded"):
        raise ADCPReceiptError("paid ADCP receipt must prove the pinned runtime was loaded")

    role_ids, role_counts = _roles(raw, allow_zero=True)
    sequence_raw = raw.get("event_sequence")
    if not isinstance(sequence_raw, list):
        raise ADCPReceiptError("event_sequence must be a list")
    event_sequence = tuple(_text(item, "event") for item in sequence_raw)
    outcome_status = _text(raw.get("outcome_status"), "outcome_status")
    if outcome_status not in PAID_OUTCOME_STATUSES:
        raise ADCPReceiptError("paid ADCP outcome status is not a canonical bounded terminal status")
    candidate_ready = _boolean(raw.get("candidate_ready"), "candidate_ready")
    if candidate_ready is not (outcome_status == "CANDIDATE_READY"):
        raise ADCPReceiptError("candidate_ready disagrees with the canonical ADCP outcome")
    if _boolean(raw.get("task_completed"), "task_completed"):
        raise ADCPReceiptError("ADCP paid boundary forbids TASK_COMPLETED authority")
    if candidate_ready:
        _require_subsequence(event_sequence, ("ARCHITECT", "CODER", "REVIEWER", "VERIFIER"))

    model_route, provider_route = _model_boundary(raw)
    model_called = _boolean(raw.get("model_called"), "model_called")
    candidate_raw = raw.get("candidate_snapshot_id")
    candidate_snapshot_id = None if candidate_raw is None else _text(candidate_raw, "candidate_snapshot_id")
    if candidate_ready and candidate_snapshot_id is None:
        raise ADCPReceiptError("CANDIDATE_READY requires a candidate snapshot id")

    paths_raw = raw.get("write_scope_paths")
    if not isinstance(paths_raw, list) or not paths_raw or not all(isinstance(path, str) and path for path in paths_raw):
        raise ADCPReceiptError("write_scope_paths must be a non-empty string list")
    write_scope_paths = tuple(paths_raw)
    if len(set(write_scope_paths)) != len(write_scope_paths):
        raise ADCPReceiptError("write_scope_paths contains duplicates")
    scope_policy = _text(raw.get("scope_policy"), "scope_policy")
    if scope_policy != ADCP_SCOPE_POLICY:
        raise ADCPReceiptError("paid ADCP receipt changed the locked write-scope policy")
    scope_digest = _text(raw.get("scope_digest"), "scope_digest")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", scope_digest) is None:
        raise ADCPReceiptError("scope_digest must be a canonical sha256 identity")
    internal_policy = _text(raw.get("internal_evaluation_policy"), "internal_evaluation_policy")
    if internal_policy != ADCP_INTERNAL_EVALUATION_POLICY:
        raise ADCPReceiptError("paid ADCP receipt changed the locked internal handoff policy")

    return ADCPPaidRunnerReceipt(
        target_runtime=target, runtime_loaded=True, role_ids=role_ids, role_call_counts=role_counts,
        event_sequence=event_sequence, outcome_status=outcome_status, candidate_ready=candidate_ready,
        task_completed=False, model_route=model_route, provider_route=provider_route,
        model_calls_via_budget_proxy=True, upstream_provider_credential_present=False,
        proxy_credential_present=True, model_called=model_called,
        session_id=_text(raw.get("session_id"), "session_id"),
        request_id=_text(raw.get("request_id"), "request_id"),
        candidate_snapshot_id=candidate_snapshot_id,
        repair_count=_non_negative_int(raw.get("repair_count"), "repair_count"),
        scope_policy=scope_policy, scope_digest=scope_digest,
        write_scope_paths=write_scope_paths, internal_evaluation_policy=internal_policy,
    )


def _model_boundary(raw: Mapping[str, object]) -> tuple[str, str]:
    model_route = _text(raw.get("model_route"), "model_route")
    provider_route = _text(raw.get("provider_route"), "provider_route")
    if model_route != ADCP_MODEL_ROUTE or provider_route != ADCP_PROVIDER_ROUTE:
        raise ADCPReceiptError("ADCP arm changed the paired model/provider identity")
    if not _boolean(raw.get("model_calls_via_budget_proxy"), "model_calls_via_budget_proxy"):
        raise ADCPReceiptError("all ADCP model calls must route through the experiment budget proxy")
    if _boolean(raw.get("upstream_provider_credential_present"), "upstream_provider_credential_present"):
        raise ADCPReceiptError("ADCP runner must not possess the upstream provider credential")
    if not _boolean(raw.get("proxy_credential_present"), "proxy_credential_present"):
        raise ADCPReceiptError("ADCP runner requires only the budget-proxy credential")
    return model_route, provider_route


def _field_error(raw: Mapping[str, object], expected: set[str]) -> None:
    missing = sorted(expected - set(raw))
    extra = sorted(set(raw) - expected)
    raise ADCPReceiptError(f"receipt fields mismatch; missing={missing}, extra={extra}")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ADCPReceiptError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ADCPReceiptError(f"{name} must be non-empty text")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ADCPReceiptError(f"{name} must be boolean")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ADCPReceiptError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ADCPReceiptError(f"{name} must be a non-negative integer")
    return value


def _require_subsequence(sequence: Sequence[str], required: Sequence[str]) -> None:
    cursor = 0
    for item in sequence:
        if cursor < len(required) and item == required[cursor]:
            cursor += 1
    if cursor != len(required):
        raise ADCPReceiptError(f"event_sequence lacks required ordered subsequence {tuple(required)}")
