"""Fail-closed contract for outcome-blind Phase 3D paid campaign mechanics."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .identity import CanonicalModel, Sha256Digest


EXPECTED_SCOPE_POLICY = "phase3d-public-static-python-scope-v2"
EXPECTED_INTERNAL_EVALUATION_POLICY = "phase3d-public-handoff-canonical-binding-v2"
EXPECTED_TASK_FAILURE_POLICY = "grade_empty_or_nonready_as_unresolved"
EXPECTED_PROXY_AUTHORITY = "benchmark_core.paid_model_proxy_cli"
EXPECTED_MAX_OUTPUT_TOKENS_PER_REQUEST = 16384
EXPECTED_SCOPE_MAX_FILES = 24
EXPECTED_SCOPE_VISIBLE_SOURCE_BYTES = 524288


class Phase3DCampaignContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Phase3DCampaignContract(CanonicalModel):
    scope_policy: str
    scope_max_files: int
    scope_visible_source_bytes: int
    internal_adcp_evaluation_policy: str
    max_output_tokens_per_request: int
    valid_task_failure_policy: str
    hidden_evaluation_material_visible_to_arms: bool
    upstream_provider_credential_visible_to_arms: bool
    proxy_budget_authority: str
    fresh_budget_proxy_per_arm: bool
    plan_digest: Sha256Digest

    @classmethod
    def from_repository(cls, root: str | Path) -> "Phase3DCampaignContract":
        path = Path(root) / "PHASE3D_EXPERIMENT_PLAN.json"
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise Phase3DCampaignContractError("cannot read locked experiment plan") from error
        if not isinstance(plan, dict) or plan.get("status") != "LOCKED":
            raise Phase3DCampaignContractError("paid campaign requires the locked experiment plan")
        campaign = plan.get("campaign")
        if not isinstance(campaign, dict):
            raise Phase3DCampaignContractError("locked plan is missing campaign mechanics")
        expected_keys = {
            "scope_policy", "scope_max_files", "scope_visible_source_bytes",
            "internal_adcp_evaluation_policy", "max_output_tokens_per_request",
            "valid_task_failure_policy", "hidden_evaluation_material_visible_to_arms",
            "upstream_provider_credential_visible_to_arms", "proxy_budget_authority",
            "fresh_budget_proxy_per_arm",
        }
        if set(campaign) != expected_keys:
            raise Phase3DCampaignContractError("campaign mechanics fields differ from the locked schema")
        result = cls(
            scope_policy=_text(campaign, "scope_policy"),
            scope_max_files=_positive(campaign, "scope_max_files"),
            scope_visible_source_bytes=_positive(campaign, "scope_visible_source_bytes"),
            internal_adcp_evaluation_policy=_text(campaign, "internal_adcp_evaluation_policy"),
            max_output_tokens_per_request=_positive(campaign, "max_output_tokens_per_request"),
            valid_task_failure_policy=_text(campaign, "valid_task_failure_policy"),
            hidden_evaluation_material_visible_to_arms=_boolean(campaign, "hidden_evaluation_material_visible_to_arms"),
            upstream_provider_credential_visible_to_arms=_boolean(campaign, "upstream_provider_credential_visible_to_arms"),
            proxy_budget_authority=_text(campaign, "proxy_budget_authority"),
            fresh_budget_proxy_per_arm=_boolean(campaign, "fresh_budget_proxy_per_arm"),
            plan_digest=Sha256Digest.of(plan),
        )
        result.require_supported()
        return result

    def require_supported(self) -> None:
        expected = {
            "scope_policy": EXPECTED_SCOPE_POLICY,
            "scope_max_files": EXPECTED_SCOPE_MAX_FILES,
            "scope_visible_source_bytes": EXPECTED_SCOPE_VISIBLE_SOURCE_BYTES,
            "internal_adcp_evaluation_policy": EXPECTED_INTERNAL_EVALUATION_POLICY,
            "max_output_tokens_per_request": EXPECTED_MAX_OUTPUT_TOKENS_PER_REQUEST,
            "valid_task_failure_policy": EXPECTED_TASK_FAILURE_POLICY,
            "hidden_evaluation_material_visible_to_arms": False,
            "upstream_provider_credential_visible_to_arms": False,
            "proxy_budget_authority": EXPECTED_PROXY_AUTHORITY,
            "fresh_budget_proxy_per_arm": True,
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise Phase3DCampaignContractError(f"unsupported/drifted paid campaign mechanic: {name}")

    def require_arm_configuration(self, *, max_output_tokens_per_request: int, scope_policy: str | None = None,
                                  internal_evaluation_policy: str | None = None) -> None:
        if max_output_tokens_per_request != self.max_output_tokens_per_request:
            raise Phase3DCampaignContractError("arm per-request output cap differs from locked campaign")
        if scope_policy is not None and scope_policy != self.scope_policy:
            raise Phase3DCampaignContractError("ADCP scope policy differs from locked campaign")
        if internal_evaluation_policy is not None and internal_evaluation_policy != self.internal_adcp_evaluation_policy:
            raise Phase3DCampaignContractError("ADCP internal evaluation policy differs from locked campaign")


def _text(source: dict[str, object], name: str) -> str:
    value = source.get(name)
    if not isinstance(value, str) or not value.strip():
        raise Phase3DCampaignContractError(f"campaign {name} must be non-empty text")
    return value


def _positive(source: dict[str, object], name: str) -> int:
    value = source.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Phase3DCampaignContractError(f"campaign {name} must be positive integer")
    return value


def _boolean(source: dict[str, object], name: str) -> bool:
    value = source.get(name)
    if not isinstance(value, bool):
        raise Phase3DCampaignContractError(f"campaign {name} must be boolean")
    return value
