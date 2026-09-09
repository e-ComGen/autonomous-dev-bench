import pytest

from suites.coding.harbor.adcp_contract import (
    ADCPRuntimeResult,
    ADCP_INTEGRATION,
    ADCP_RUNTIME_COMMIT,
    ADCP_RUNTIME_ENTRYPOINT,
    ADCP_RUNTIME_REPOSITORY,
    SHARED_MODEL_ROUTE,
)


def payload(**overrides):
    value = {
        "runtime_repository": ADCP_RUNTIME_REPOSITORY,
        "runtime_commit": ADCP_RUNTIME_COMMIT,
        "runtime_entrypoint": ADCP_RUNTIME_ENTRYPOINT,
        "integration": ADCP_INTEGRATION,
        "model_route": SHARED_MODEL_ROUTE,
        "direct_model_api_used": False,
        "outcome": "CANDIDATE_READY",
        "role_calls": 7,
        "roles_seen": ["architect", "coder", "reviewer", "verifier"],
        "evidence": ["cas:sha256:" + "a" * 64],
        "model_accounting": {
            "requests": 7,
            "input_tokens": 100,
            "output_tokens": 40,
            "reasoning_tokens": 5,
            "cache_tokens": 20,
            "cost_usd_micros": 300,
            "accounting_valid": True,
            "violations": [],
        },
        "metadata": {"repairs": 1},
    }
    value.update(overrides)
    return value


def test_accepts_exact_pinned_runtime_and_shared_gateway_route():
    result = ADCPRuntimeResult.from_mapping(payload())

    assert result.runtime_commit == ADCP_RUNTIME_COMMIT
    assert result.model_route == SHARED_MODEL_ROUTE
    assert result.direct_model_api_used is False
    assert result.outcome == "CANDIDATE_READY"
    assert result.role_calls == 7
    assert result.model_accounting.total_model_tokens == 140
    assert result.model_accounting.requests == 7


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("runtime_repository", "other/repo"),
        ("runtime_commit", "0" * 40),
        ("runtime_entrypoint", "other.Runtime"),
        ("integration", "replacement-loop"),
        ("model_route", "direct-deepseek"),
    ],
)
def test_rejects_runtime_or_route_identity_drift(field, bad):
    with pytest.raises(ValueError, match="mismatch"):
        ADCPRuntimeResult.from_mapping(payload(**{field: bad}))


def test_rejects_direct_model_api_use():
    with pytest.raises(ValueError, match="must not use a direct model API"):
        ADCPRuntimeResult.from_mapping(payload(direct_model_api_used=True))


def test_candidate_ready_requires_all_four_distinct_role_classes():
    with pytest.raises(ValueError, match="missing required role evidence"):
        ADCPRuntimeResult.from_mapping(payload(roles_seen=["architect", "coder", "reviewer"]))


def test_candidate_ready_requires_valid_nonviolating_accounting():
    bad = dict(payload()["model_accounting"])
    bad["accounting_valid"] = False
    with pytest.raises(ValueError, match="valid, non-violating"):
        ADCPRuntimeResult.from_mapping(payload(model_accounting=bad))

    bad = dict(payload()["model_accounting"])
    bad["violations"] = ["total_model_token_cap"]
    with pytest.raises(ValueError, match="valid, non-violating"):
        ADCPRuntimeResult.from_mapping(payload(model_accounting=bad))


def test_non_terminal_outcome_can_report_partial_role_execution_and_budget_stop():
    accounting = dict(payload()["model_accounting"])
    accounting["violations"] = ["total_model_token_cap"]
    result = ADCPRuntimeResult.from_mapping(
        payload(
            outcome="BLOCKED",
            roles_seen=["architect"],
            role_calls=1,
            evidence=[],
            model_accounting=accounting,
        )
    )
    assert result.outcome == "BLOCKED"
    assert result.roles_seen == ("architect",)
    assert result.model_accounting.violations == ("total_model_token_cap",)
