from dataclasses import replace

import pytest

from benchmark_core.experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ExperimentManifest,
    ModelManifest,
    TaskManifest,
    TrialManifest,
)
from benchmark_core.paired_experiment import PairedExperimentManifest, SHARED_MODEL_ROUTE


SHA = "sha256:" + "a" * 64
COMMIT = "1" * 40


def arm(agent: str, *, seed=17, budget=None, model=None, execution=None, route=SHARED_MODEL_ROUTE):
    return ExperimentManifest(
        experiment_id=f"pair-{agent}",
        task=TaskManifest(
            dataset="swebench_verified",
            dataset_version="v5",
            task_id="sympy__sympy-20590",
            task_repo_commit=COMMIT,
            environment_image_digest=SHA,
            evaluator_version="5.0.2",
        ),
        agent=AgentManifest(
            implementation=agent,
            commit=COMMIT,
            configuration={"model_route": route},
        ),
        model=model
        or ModelManifest(
            identifier="deepseek-v4-flash",
            provider_route="shared-gateway/deepseek",
            decoding={"temperature": 0},
        ),
        budget=budget
        or BudgetManifest(
            input_token_cap=1000,
            output_token_cap=500,
            total_model_token_cap=1200,
            max_requests=20,
            wall_time_seconds=1800,
            patch_byte_cap=100000,
        ),
        execution=execution
        or ExecutionManifest(
            engine="harbor",
            engine_version="0.22.0",
            provider="wsl2_docker_engine",
            network_policy="model_gateway_only",
            resource_policy={"cpu": 4, "memory_mb": 8192},
        ),
        trial=TrialManifest(repeat_index=0, seed=seed),
    )


def test_pair_admits_only_agent_orchestration_difference():
    pair = PairedExperimentManifest("sympy-20590-r0", arm("stock_deepseek"), arm("adcp"))
    evidence = pair.as_admission_evidence()
    assert evidence["status"] == "ADMITTED"
    assert evidence["model_route"] == SHARED_MODEL_ROUTE
    assert pair.fairness_budget.total_model_token_cap == 1200


@pytest.mark.parametrize("difference", ["task", "model", "budget", "execution", "seed"])
def test_pair_rejects_causal_confounds(difference):
    stock = arm("stock_deepseek")
    adcp = arm("adcp")
    if difference == "task":
        adcp = replace(adcp, task=replace(adcp.task, task_id="pytest-dev__pytest-10081"))
    elif difference == "model":
        adcp = replace(adcp, model=replace(adcp.model, identifier="other-model"))
    elif difference == "budget":
        adcp = replace(adcp, budget=replace(adcp.budget, total_model_token_cap=1199))
    elif difference == "execution":
        adcp = replace(adcp, execution=replace(adcp.execution, provider="different-provider"))
    elif difference == "seed":
        adcp = replace(adcp, trial=replace(adcp.trial, seed=18))

    with pytest.raises(ValueError, match="paired arms"):
        PairedExperimentManifest("confounded", stock, adcp)


def test_pair_rejects_any_arm_outside_shared_gateway():
    with pytest.raises(ValueError, match="stock arm must use"):
        PairedExperimentManifest(
            "bad-stock-route",
            arm("stock_deepseek", route="direct-provider"),
            arm("adcp"),
        )
    with pytest.raises(ValueError, match="adcp arm must use"):
        PairedExperimentManifest(
            "bad-adcp-route",
            arm("stock_deepseek"),
            arm("adcp", route="direct-provider"),
        )


def test_pair_rejects_identical_agent_manifest():
    stock = arm("stock_deepseek")
    duplicate = replace(stock, experiment_id="duplicate")
    with pytest.raises(ValueError, match="distinct agent"):
        PairedExperimentManifest("same-agent", stock, duplicate)
