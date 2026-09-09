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
from .project import ProjectSpec
from .result import HardGate, OracleResult, RunResult, RunStatus, StageResult, SuiteResult, SystemObservation
from .runner import BenchmarkSuite, ExperimentRunner, RunContext, SystemAdapter
from .sandbox import DockerSandboxProvider
from .scenario import ScenarioSpec
from .swebench_v5 import OfficialSwebenchV5, SwebenchPrediction, require_v5, write_predictions
from .task import TaskSpec

__all__ = [
    "AgentManifest",
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
    "EnvironmentBuildResult",
    "ExactRequestBudgetEstimator",
    "ExactTokenEstimateUnavailable",
    "ExecutionManifest",
    "ExperimentManifest",
    "ExperimentRunner",
    "ExperimentSpec",
    "FrozenDict",
    "HardGate",
    "InvalidExperiment",
    "ModelBudgetGateway",
    "ModelBudgetSnapshot",
    "ModelCallReservation",
    "ModelManifest",
    "ModelUsage",
    "OfficialSwebenchV5",
    "OracleResult",
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
    "canonical_json",
    "load_project",
    "load_scenario",
    "load_suite",
    "load_task",
    "require_v5",
    "write_predictions",
]

__version__ = "0.1.0"
