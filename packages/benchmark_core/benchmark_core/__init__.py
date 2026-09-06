"""Reusable neutral core for autonomous development benchmarks.

Production packages must not import this package. Benchmark adapters may import
normal production APIs and translate their outputs into these neutral records.
"""

from .bootstrap import EnvironmentBuildResult, ProjectEnvironmentBuilder
from .experiment import ExperimentSpec, SuitePlan, SystemUnderTest
from .identity import CanonicalModel, CommitPin, FrozenDict, Sha256Digest, VersionIdentity, canonical_json
from .isolation import SandboxTrustStore
from .manifest import load_project, load_scenario, load_suite, load_task
from .overlay import InvalidExperiment, ScenarioCheckpointMaterializer
from .project import ProjectSpec
from .result import HardGate, OracleResult, RunResult, RunStatus, StageResult, SuiteResult, SystemObservation
from .runner import BenchmarkSuite, ExperimentRunner, RunContext, SystemAdapter
from .sandbox import DockerSandboxProvider
from .scenario import ScenarioSpec
from .task import TaskSpec

__all__ = [
    "BenchmarkSuite",
    "CanonicalModel",
    "CommitPin",
    "DockerSandboxProvider",
    "EnvironmentBuildResult",
    "ExperimentRunner",
    "ExperimentSpec",
    "FrozenDict",
    "HardGate",
    "OracleResult",
    "ProjectEnvironmentBuilder",
    "ProjectSpec",
    "RunContext",
    "RunResult",
    "RunStatus",
    "SandboxTrustStore",
    "ScenarioSpec",
    "Sha256Digest",
    "StageResult",
    "SuitePlan",
    "SuiteResult",
    "SystemAdapter",
    "SystemObservation",
    "SystemUnderTest",
    "TaskSpec",
    "VersionIdentity",
    "canonical_json",
    "load_project",
    "load_scenario",
    "load_task",
    "load_suite",
    "InvalidExperiment",
    "ScenarioCheckpointMaterializer",
]

__version__ = "0.1.0"
