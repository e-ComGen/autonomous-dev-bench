"""Causal pairing invariants for Stock-vs-ADCP benchmark arms."""

from __future__ import annotations

from dataclasses import dataclass

from .experiment_manifest import ExperimentManifest
from .identity import CanonicalModel, require_identifier


SHARED_MODEL_ROUTE = "shared_budget_gateway"


@dataclass(frozen=True, slots=True)
class PairedExperimentManifest(CanonicalModel):
    """Two arms that may differ only in agent/orchestration identity.

    Task, model, budget, execution environment and stochastic repeat identity
    must be identical. This is the static admission gate for a causal A/B run;
    actual token consumption may differ and is an outcome, but both arms receive
    the same caps and the same model route.
    """

    pair_id: str
    stock: ExperimentManifest
    adcp: ExperimentManifest
    schema_version: str = "1"

    def __post_init__(self) -> None:
        require_identifier(self.pair_id, "pair_id")
        require_identifier(self.schema_version, "schema_version")
        if self.stock.outputs is not None or self.adcp.outputs is not None:
            raise ValueError("paired admission manifests must be pre-run and must not contain outputs")
        if self.stock.task != self.adcp.task:
            raise ValueError("paired arms must use the exact same task manifest")
        if self.stock.model != self.adcp.model:
            raise ValueError("paired arms must use the exact same model manifest")
        if self.stock.budget != self.adcp.budget:
            raise ValueError("paired arms must use the exact same budget manifest")
        if self.stock.execution != self.adcp.execution:
            raise ValueError("paired arms must use the exact same execution manifest")
        if (self.stock.trial.repeat_index, self.stock.trial.seed) != (
            self.adcp.trial.repeat_index,
            self.adcp.trial.seed,
        ):
            raise ValueError("paired arms must use the same repeat index and seed")
        if self.stock.agent == self.adcp.agent:
            raise ValueError("paired arms must have distinct agent/orchestration manifests")
        for arm_name, manifest in (("stock", self.stock), ("adcp", self.adcp)):
            route = manifest.agent.configuration.get("model_route")
            if route != SHARED_MODEL_ROUTE:
                raise ValueError(
                    f"{arm_name} arm must use model_route={SHARED_MODEL_ROUTE!r}; observed {route!r}"
                )

    @property
    def fairness_budget(self):
        return self.stock.budget

    @property
    def model(self):
        return self.stock.model

    def as_admission_evidence(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "status": "ADMITTED",
            "primary_fairness_metric": "total_model_tokens",
            "total_model_tokens_definition": "input_tokens + output_tokens",
            "model_route": SHARED_MODEL_ROUTE,
            "task_digest": str(self.stock.task.content_digest),
            "model_digest": str(self.stock.model.content_digest),
            "budget_digest": str(self.stock.budget.content_digest),
            "execution_digest": str(self.stock.execution.content_digest),
            "repeat_index": self.stock.trial.repeat_index,
            "seed": self.stock.trial.seed,
            "stock_agent_digest": str(self.stock.agent.content_digest),
            "adcp_agent_digest": str(self.adcp.agent.content_digest),
        }
