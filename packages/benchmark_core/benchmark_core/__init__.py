"""Reusable neutral core for autonomous development benchmarks.

Production packages must not import this package. Benchmark adapters may import
normal production APIs and translate their outputs into these neutral records.
"""

from .bootstrap import EnvironmentBuildResult, ProjectEnvironmentBuilder
from .deepseek_v4_estimator import (
    DEEPSEEK_V4_ENCODING_FILE,
    DEEPSEEK_V4_MODEL,
    DEEPSEEK_V4_REPO_ID,
    DEEPSEEK_V4_REVISION,
    DeepSeekV4EstimatorAssetError,
    DeepSeekV4EstimatorIdentity,
    DeepSeekV4RequestEstimator,
)
from .experiment import ExperimentSpec, SuitePlan, SystemUnderTest
from .experiment_manifest import (
    AgentManifest,
    BudgetManifest,
    ExecutionManifest,
    ExperimentManifest,
    ModelManifest,
    TaskManifest,
    TrialManifest,
    TrialOutputs,
)
from .experiment_preregistration import (
    ExperimentDesignSnapshot,
    ExperimentPlanInvalid,
    PAIR_ID_TEMPLATE,
    PAIR_SEED_ALGORITHM,
)
from .identity import CanonicalModel, CommitPin, FrozenDict, Sha256Digest, VersionIdentity, canonical_json
from .isolation import SandboxTrustStore
from .manifest import load_project, load_scenario, load_suite, load_task
from .model_budget import (
    BudgetAccountingError,
    BudgetExceeded,
    ModelBudgetGateway,
    ModelBudgetSnapshot,
    ModelCallReservation,
    ModelUsage,
)
from .model_proxy import (
    BudgetedModelProxyCore,
    BudgetProxySnapshot,
    ExactRequestBudgetEstimator,
    ExactTokenEstimateUnavailable,
    PinnedRequestEstimator,
    ProviderUsageMissing,
    ProxyAdmission,
    RequestBudgetEstimate,
)
from .model_proxy_http import BudgetProxyHttpConfig, BudgetProxyHttpServer
from .overlay import InvalidExperiment, ScenarioCheckpointMaterializer
from .paired_analysis import (
    ExclusionReason,
    ExperimentWinner,
    IncompletePairedSchedule,
    PairOutcomeAttempt,
    PairOutcomeSummary,
    PairScheduleEntry,
    PairedAnalysisError,
    PairedBinaryAnalysisReport,
    PairedExperimentSchedule,
    PairedLedgerAudit,
    analyze_final_paired_binary,
    audit_paired_ledger,
    exact_mcnemar_two_sided,
)
from .paired_analysis_contract import (
    EXPECTED_ANALYSIS_CONTRACT,
    PairedAnalysisContract,
    PairedAnalysisContractError,
    validate_paired_analysis_preregistration,
)
from .paired_experiment import (
    ArmExecutionReceipt,
    DryRunModelCallForbidden,
    ExperimentArm,
    PairFairnessError,
    PaidAdmissionSnapshot,
    PaidExperimentBlocked,
    PairedArmExecutor,
    PairedExperimentController,
    PairedExperimentPlan,
    PairedRunReceipt,
    require_causal_pair,
)
from .project import ProjectSpec
from .result import HardGate, OracleResult, RunResult, RunStatus, StageResult, SuiteResult, SystemObservation
from .runner import BenchmarkSuite, ExperimentRunner, RunContext, SystemAdapter
from .sandbox import DockerSandboxProvider
from .scenario import ScenarioSpec
from .swebench_v5 import OfficialSwebenchV5, SwebenchPrediction, require_v5, write_predictions
from .task import TaskSpec

__all__ = [
    "AgentManifest",
    "ArmExecutionReceipt",
    "BenchmarkSuite",
    "BudgetAccountingError",
    "BudgetExceeded",
    "BudgetManifest",
    "BudgetedModelProxyCore",
    "BudgetProxyHttpConfig",
    "BudgetProxyHttpServer",
    "BudgetProxySnapshot",
    "CanonicalModel",
    "CommitPin",
    "DEEPSEEK_V4_ENCODING_FILE",
    "DEEPSEEK_V4_MODEL",
    "DEEPSEEK_V4_REPO_ID",
    "DEEPSEEK_V4_REVISION",
    "DeepSeekV4EstimatorAssetError",
    "DeepSeekV4EstimatorIdentity",
    "DeepSeekV4RequestEstimator",
    "DockerSandboxProvider",
    "DryRunModelCallForbidden",
    "EXPECTED_ANALYSIS_CONTRACT",
    "EnvironmentBuildResult",
    "ExactRequestBudgetEstimator",
    "ExactTokenEstimateUnavailable",
    "ExecutionManifest",
    "ExclusionReason",
    "ExperimentArm",
    "ExperimentDesignSnapshot",
    "ExperimentManifest",
    "ExperimentPlanInvalid",
    "ExperimentRunner",
    "ExperimentSpec",
    "ExperimentWinner",
    "FrozenDict",
    "HardGate",
    "IncompletePairedSchedule",
    "InvalidExperiment",
    "ModelBudgetGateway",
    "ModelBudgetSnapshot",
    "ModelCallReservation",
    "ModelManifest",
    "ModelUsage",
    "OfficialSwebenchV5",
    "OracleResult",
    "PAIR_ID_TEMPLATE",
    "PAIR_SEED_ALGORITHM",
    "PairFairnessError",
    "PairOutcomeAttempt",
    "PairOutcomeSummary",
    "PairScheduleEntry",
    "PaidAdmissionSnapshot",
    "PaidExperimentBlocked",
    "PairedAnalysisContract",
    "PairedAnalysisContractError",
    "PairedAnalysisError",
    "PairedArmExecutor",
    "PairedBinaryAnalysisReport",
    "PairedExperimentController",
    "PairedExperimentPlan",
    "PairedExperimentSchedule",
    "PairedLedgerAudit",
    "PairedRunReceipt",
    "PinnedRequestEstimator",
    "ProjectEnvironmentBuilder",
    "ProjectSpec",
    "ProviderUsageMissing",
    "ProxyAdmission",
    "RequestBudgetEstimate",
    "RunContext",
    "RunResult",
    "RunStatus",
    "SandboxTrustStore",
    "ScenarioCheckpointMaterializer",
    "ScenarioSpec",
    "Sha256Digest",
    "StageResult",
    "SuitePlan",
    "SuiteResult",
    "SwebenchPrediction",
    "SystemAdapter",
    "SystemObservation",
    "SystemUnderTest",
    "TaskManifest",
    "TaskSpec",
    "TrialManifest",
    "TrialOutputs",
    "VersionIdentity",
    "analyze_final_paired_binary",
    "audit_paired_ledger",
    "canonical_json",
    "exact_mcnemar_two_sided",
    "load_project",
    "load_scenario",
    "load_suite",
    "load_task",
    "require_causal_pair",
    "require_v5",
    "validate_paired_analysis_preregistration",
    "write_predictions",
]

__version__ = "0.1.0"
