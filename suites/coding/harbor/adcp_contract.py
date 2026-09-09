"""Pure transport contract for the orchestrated ADCP benchmark arm.

This module intentionally contains no orchestration logic. The benchmark only
validates the identity and accounting route of the external pinned runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping


ADCP_RUNTIME_REPOSITORY = "e-ComGen/autonomous-dev-control-plane"
ADCP_RUNTIME_COMMIT = "285702063815280398b95ba8696566259c8b5b34"
ADCP_RUNTIME_ENTRYPOINT = "packages.zone_development.assured_runtime.ZoneDevelopmentRuntime"
ADCP_INTEGRATION = "existing-v2-runtime-role-ports"
SHARED_MODEL_ROUTE = "shared_budget_gateway"
_REQUIRED_ROLES = frozenset({"architect", "coder", "reviewer", "verifier"})


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ADCPModelAccounting:
    requests: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_tokens: int
    cost_usd_micros: int
    accounting_valid: bool
    violations: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: object) -> "ADCPModelAccounting":
        if not isinstance(payload, dict):
            raise ValueError("ADCP model_accounting must be a JSON object")
        values = {
            field: _non_negative_int(payload.get(field), field)
            for field in (
                "requests",
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cache_tokens",
                "cost_usd_micros",
            )
        }
        valid = payload.get("accounting_valid")
        if not isinstance(valid, bool):
            raise ValueError("model_accounting.accounting_valid must be boolean")
        violations_raw = payload.get("violations", [])
        if not isinstance(violations_raw, list) or not all(
            isinstance(value, str) and value for value in violations_raw
        ):
            raise ValueError("model_accounting.violations must be a list of non-empty strings")
        return cls(
            **values,
            accounting_valid=valid,
            violations=tuple(violations_raw),
        )

    @property
    def total_model_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, object]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_model_tokens": self.total_model_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_tokens": self.cache_tokens,
            "cost_usd_micros": self.cost_usd_micros,
            "accounting_valid": self.accounting_valid,
            "violations": list(self.violations),
        }


@dataclass(frozen=True, slots=True)
class ADCPRuntimeResult:
    runtime_repository: str
    runtime_commit: str
    runtime_entrypoint: str
    integration: str
    model_route: str
    direct_model_api_used: bool
    outcome: str
    role_calls: int
    roles_seen: tuple[str, ...]
    evidence: tuple[str, ...]
    model_accounting: ADCPModelAccounting
    metadata: Mapping[str, object]

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ADCPRuntimeResult":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ADCP runtime result must contain a JSON object")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ADCPRuntimeResult":
        expected = {
            "runtime_repository": ADCP_RUNTIME_REPOSITORY,
            "runtime_commit": ADCP_RUNTIME_COMMIT,
            "runtime_entrypoint": ADCP_RUNTIME_ENTRYPOINT,
            "integration": ADCP_INTEGRATION,
            "model_route": SHARED_MODEL_ROUTE,
        }
        for field, required in expected.items():
            if payload.get(field) != required:
                raise ValueError(f"ADCP {field} mismatch: expected {required!r}, observed {payload.get(field)!r}")

        direct = payload.get("direct_model_api_used")
        if direct is not False:
            raise ValueError("ADCP runtime must not use a direct model API route")

        outcome = payload.get("outcome")
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("ADCP outcome must be a non-empty string")

        role_calls = _non_negative_int(payload.get("role_calls"), "role_calls")
        roles_raw = payload.get("roles_seen", [])
        if not isinstance(roles_raw, list) or not all(isinstance(role, str) and role for role in roles_raw):
            raise ValueError("roles_seen must be a list of non-empty strings")
        roles = tuple(roles_raw)
        if outcome == "CANDIDATE_READY" and not _REQUIRED_ROLES.issubset(set(roles)):
            missing = sorted(_REQUIRED_ROLES - set(roles))
            raise ValueError(f"CANDIDATE_READY result is missing required role evidence: {missing}")

        evidence_raw = payload.get("evidence", [])
        if not isinstance(evidence_raw, list) or not all(isinstance(value, str) and value for value in evidence_raw):
            raise ValueError("evidence must be a list of non-empty strings")

        accounting = ADCPModelAccounting.from_mapping(payload.get("model_accounting"))
        if outcome == "CANDIDATE_READY" and (not accounting.accounting_valid or accounting.violations):
            raise ValueError("CANDIDATE_READY requires valid, non-violating shared model accounting")

        metadata_raw = payload.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            raise ValueError("metadata must be a JSON object")

        return cls(
            runtime_repository=ADCP_RUNTIME_REPOSITORY,
            runtime_commit=ADCP_RUNTIME_COMMIT,
            runtime_entrypoint=ADCP_RUNTIME_ENTRYPOINT,
            integration=ADCP_INTEGRATION,
            model_route=SHARED_MODEL_ROUTE,
            direct_model_api_used=False,
            outcome=outcome,
            role_calls=role_calls,
            roles_seen=roles,
            evidence=tuple(evidence_raw),
            model_accounting=accounting,
            metadata=dict(metadata_raw),
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "runtime_repository": self.runtime_repository,
            "runtime_commit": self.runtime_commit,
            "runtime_entrypoint": self.runtime_entrypoint,
            "integration": self.integration,
            "model_route": self.model_route,
            "direct_model_api_used": self.direct_model_api_used,
            "outcome": self.outcome,
            "role_calls": self.role_calls,
            "roles_seen": list(self.roles_seen),
            "evidence": list(self.evidence),
            "model_accounting": self.model_accounting.as_dict(),
            "metadata": dict(self.metadata),
        }
