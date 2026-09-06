"""Execute Auto-Refactoring's benchmark-owned safety probes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from benchmark_core.result import RunStatus, SystemObservation
from oracles import DifferentialOracle, FunctionalOracle, PublicApiOracle

from .suite import RefactoringLabels, RefactoringOracleContext


@dataclass(frozen=True, slots=True)
class RefactoringOracleExecutor:
    """Build private context from executed probes, never SUT assertions."""

    labels: RefactoringLabels
    functional_checks: Callable[[Path], Mapping[str, Callable[[], object] | bool]]
    baseline_observable: object
    candidate_observable: Callable[[Path], object]
    baseline_public_api: object
    candidate_public_api: Callable[[Path], object]
    mutation_presence_probe: Callable[[Path], bool]
    design_opportunity_probe: Callable[[Path], bool]

    def __call__(self, workspace: Path, observation: SystemObservation) -> RefactoringOracleContext:
        functional = FunctionalOracle("functional-regression", "v2").evaluate(self.functional_checks(workspace))
        differential = DifferentialOracle("differential-behavior", "v1").evaluate(
            self.baseline_observable, self.candidate_observable(workspace)
        )
        public_api = PublicApiOracle("public-api", "v2").evaluate(
            self.baseline_public_api, self.candidate_public_api(workspace)
        )
        try:
            mutation_observed = bool(self.mutation_presence_probe(workspace))
            mutation_error = None
        except BaseException as exc:
            mutation_observed = None
            mutation_error = f"{type(exc).__name__}: {exc}"
        try:
            design_observed = bool(self.design_opportunity_probe(workspace))
            design_error = None
        except BaseException as exc:
            design_observed = None
            design_error = f"{type(exc).__name__}: {exc}"
        mutation_verified = mutation_error is None and mutation_observed is self.labels.mutation_present
        design_verified = design_error is None and design_observed is self.labels.design_opportunity
        return RefactoringOracleContext(
            labels=self.labels,
            functional_preserved=functional.status is RunStatus.PASS,
            differential_preserved=differential.status is RunStatus.PASS,
            public_api_preserved=public_api.status is RunStatus.PASS,
            mutation_presence_verified=mutation_verified,
            design_opportunity_verified=design_verified,
            mutation_evidence={"observed": mutation_observed, "expected": self.labels.mutation_present, "error": mutation_error},
            design_evidence={
                "observed": design_observed, "expected": self.labels.design_opportunity, "error": design_error,
                "functional_oracle": functional.measurements,
                "differential_oracle": differential.measurements,
                "public_api_oracle": public_api.measurements,
            },
        )
