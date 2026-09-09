import pytest

from benchmark_core.experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ExperimentManifest,
    ModelManifest,
    TaskManifest,
    TrialManifest,
    TrialOutputs,
)


SHA = "sha256:" + "a" * 64
COMMIT = "1" * 40


def manifest() -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="verified-stock-task-0",
        task=TaskManifest(
            dataset="swebench_verified",
            dataset_version="v5",
            task_id="sympy__sympy-20590",
            task_repo_commit=COMMIT,
            environment_image_digest=SHA,
            evaluator_version="5.0.2",
        ),
        agent=AgentManifest(
            implementation="stock_deepseek",
            commit=COMMIT,
            configuration={"prompt": "stock"},
            ablation_flags={"reviewer": False},
        ),
        model=ModelManifest(
            identifier="deepseek-chat",
            provider_route="provider/deepseek",
            decoding={"temperature": 0},
            pricing_snapshot={"currency": "USD", "input_per_million": 1},
        ),
        budget=BudgetManifest(
            input_token_cap=100000,
            output_token_cap=50000,
            total_model_token_cap=120000,
            max_requests=64,
            wall_time_seconds=3600,
            patch_byte_cap=1000000,
        ),
        execution=ExecutionManifest(
            engine="direct_swebench",
            engine_version="phase1",
            provider="remote_linux",
            network_policy="no_network",
            resource_policy={"cpu": 8, "memory_mb": 16384},
        ),
        trial=TrialManifest(repeat_index=0, seed=17, started_at="2026-09-08T18:00:00Z"),
    )


def test_manifest_is_canonical_and_finalizable():
    pending = manifest()
    assert pending.outputs is None
    assert pending.identity == pending.content_digest

    finished = pending.finalize(
        TrialOutputs(
            patch_digest=SHA,
            trajectory_digest=SHA,
            telemetry_digest=SHA,
            evaluator_result="PASS",
        ),
        "2026-09-08T18:10:00Z",
    )

    assert finished.outputs is not None
    assert finished.trial.finished_at == "2026-09-08T18:10:00Z"
    assert finished.content_digest != pending.content_digest


def test_manifest_rejects_finished_trial_without_outputs():
    pending = manifest()
    with pytest.raises(ValueError, match="finished trials require outputs"):
        ExperimentManifest(
            experiment_id=pending.experiment_id,
            task=pending.task,
            agent=pending.agent,
            model=pending.model,
            budget=pending.budget,
            execution=pending.execution,
            trial=TrialManifest(
                repeat_index=0,
                seed=17,
                started_at="2026-09-08T18:00:00Z",
                finished_at="2026-09-08T18:10:00Z",
            ),
        )


def test_budget_rejects_request_count_as_zero():
    with pytest.raises(ValueError, match="max_requests"):
        BudgetManifest(1, 1, 1, 0, 1, 1)
