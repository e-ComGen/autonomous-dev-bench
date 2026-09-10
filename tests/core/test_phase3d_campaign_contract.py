from pathlib import Path
import json
import shutil

import pytest

from benchmark_core.phase3d_campaign_contract import (
    CAMPAIGN_POLICY_FILE,
    EXPECTED_INTERNAL_EVALUATION_POLICY,
    EXPECTED_MAX_OUTPUT_TOKENS_PER_REQUEST,
    EXPECTED_SCOPE_POLICY,
    Phase3DCampaignContract,
    Phase3DCampaignContractError,
)

ROOT = Path(__file__).resolve().parents[2]


def test_repository_campaign_contract_is_locked_and_supported():
    contract = Phase3DCampaignContract.from_repository(ROOT)
    assert contract.scope_policy == EXPECTED_SCOPE_POLICY
    assert contract.internal_adcp_evaluation_policy == EXPECTED_INTERNAL_EVALUATION_POLICY
    assert contract.max_output_tokens_per_request == EXPECTED_MAX_OUTPUT_TOKENS_PER_REQUEST
    assert not contract.hidden_evaluation_material_visible_to_arms
    assert not contract.upstream_provider_credential_visible_to_arms
    assert contract.fresh_budget_proxy_per_arm


def test_campaign_mechanic_drift_does_not_mutate_design_lock_and_fails_closed(tmp_path: Path):
    plan_source = ROOT / "PHASE3D_EXPERIMENT_PLAN.json"
    plan_target = tmp_path / plan_source.name
    shutil.copyfile(plan_source, plan_target)
    policy_source = ROOT / CAMPAIGN_POLICY_FILE
    policy_target = tmp_path / CAMPAIGN_POLICY_FILE
    shutil.copyfile(policy_source, policy_target)

    original = Phase3DCampaignContract.from_repository(tmp_path)
    original_plan_bytes = plan_target.read_bytes()
    policy = json.loads(policy_target.read_text(encoding="utf-8"))
    policy["max_output_tokens_per_request"] = 2048
    policy_target.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(Phase3DCampaignContractError, match="max_output_tokens_per_request"):
        Phase3DCampaignContract.from_repository(tmp_path)
    assert plan_target.read_bytes() == original_plan_bytes
    assert str(original.plan_digest).startswith("sha256:")


def test_outcome_or_paid_state_in_campaign_policy_fails_closed(tmp_path: Path):
    plan_source = ROOT / "PHASE3D_EXPERIMENT_PLAN.json"
    shutil.copyfile(plan_source, tmp_path / plan_source.name)
    policy_source = ROOT / CAMPAIGN_POLICY_FILE
    policy = json.loads(policy_source.read_text(encoding="utf-8"))
    policy["outcome_data_used"] = True
    (tmp_path / CAMPAIGN_POLICY_FILE).write_text(
        json.dumps(policy, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(Phase3DCampaignContractError, match="outcome-blind"):
        Phase3DCampaignContract.from_repository(tmp_path)


def test_arm_configuration_must_match_locked_campaign():
    contract = Phase3DCampaignContract.from_repository(ROOT)
    contract.require_arm_configuration(
        max_output_tokens_per_request=EXPECTED_MAX_OUTPUT_TOKENS_PER_REQUEST,
        scope_policy=EXPECTED_SCOPE_POLICY,
        internal_evaluation_policy=EXPECTED_INTERNAL_EVALUATION_POLICY,
    )
    with pytest.raises(Phase3DCampaignContractError):
        contract.require_arm_configuration(max_output_tokens_per_request=2048)
