"""Host-side arm executors for the durable Phase 3D paired campaign.

``DurablePhase3DCampaign`` owns the schedule, the durable per-attempt state, the
resume rules and the exclusion taxonomy. This module owns the two things it
delegates:

* :class:`CampaignPairExecutor` — run exactly one Harbor trial for one arm and
  return the durable arm artifact, and
* :class:`CampaignOfficialGrader` — score that arm's patch with the pinned
  official evaluator.

Harbor runs in WSL2 with the Linux Docker engine, so the launcher shells out.
Neither the executor nor the grader decides a winner or re-derives a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Mapping, Protocol, runtime_checkable

from benchmark_core.experiment_manifest import ExperimentManifest
from benchmark_core.identity import Sha256Digest
from benchmark_core.paired_experiment import (
    ArmExecutionReceipt,
    ExperimentArm,
    PairedExperimentPlan,
)
from benchmark_core.phase3d_campaign import (
    CampaignArmArtifact,
    ExperimentAccountingUnknownFailure,
    OfficialGradeArtifact,
    PreDispatchInfrastructureFailure,
)
from benchmark_core.swebench_v5 import (
    OfficialResolution,
    OfficialSwebenchV5,
    SwebenchPrediction,
    official_outcome,
    write_predictions,
)


STOCK_AGENT = "suites.coding.harbor.stock_agent:StockDeepSeekAgent"
ADCP_AGENT = "suites.coding.harbor.adcp_agent:ADCPHarborAgent"
STOCK_FAKE_ENV = "AUTOBENCH_FAKE_MODEL"
ADCP_FAKE_ENV = "AUTOBENCH_ADCP_FAKE_RUNTIME"
HARBOR_VENV = "$HOME/.cache/autobench-product-readiness-harbor-venv"


class ArmExecutionError(RuntimeError):
    """The trial started but did not produce a usable result (possibly post-dispatch)."""


def sha256_text(value: str) -> Sha256Digest:
    return Sha256Digest("sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------------------
# Harbor trial boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HarborTrialRequest:
    task_dir: Path
    agent_import_path: str
    trial_name: str
    trials_dir: Path
    controller_env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        if not isinstance(self.task_dir, Path) or not isinstance(self.trials_dir, Path):
            raise TypeError("task_dir and trials_dir must be Path values")
        if not self.agent_import_path.strip() or not self.trial_name.strip():
            raise ValueError("agent_import_path and trial_name must be non-empty")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class HarborTrialResult:
    """What one finished Harbor trial yields for the campaign."""

    trial_dir: Path
    agent_metadata: Mapping[str, object]
    patch: str

    def metadata(self, name: str, default: object = None) -> object:
        return self.agent_metadata.get(name, default)


@runtime_checkable
class HarborTrialLauncher(Protocol):
    def launch(self, request: HarborTrialRequest) -> HarborTrialResult:
        """Run exactly one Harbor trial and return its durable artifacts."""


class WslHarborLauncher:
    """Launch Harbor through WSL2 + the Linux Docker engine, per the locked host profile."""

    def __init__(
        self,
        *,
        bench_root: Path,
        harbor_root: Path,
        venv: str = HARBOR_VENV,
        install: bool = True,
        runner=None,
    ) -> None:
        self.bench_root = Path(bench_root).resolve()
        self.harbor_root = Path(harbor_root).resolve()
        self.venv = venv
        self.install = install
        self._runner = runner or self._default_runner

    def launch(self, request: HarborTrialRequest) -> HarborTrialResult:
        if not request.task_dir.is_dir():
            raise PreDispatchInfrastructureFailure(f"Harbor task directory missing: {request.task_dir}")
        stdout = self._runner(self._script(request), request.timeout_seconds + 600)
        trial_dir = request.trials_dir / request.trial_name
        result_path = trial_dir / "result.json"
        if not result_path.is_file():
            # The trial may have started before failing, so this is not provably
            # pre-dispatch: fail closed and let the campaign classify it.
            raise ArmExecutionError(f"Harbor trial produced no result.json at {result_path}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ArmExecutionError("Harbor trial result.json must be an object")
        exception = payload.get("exception_info")
        if isinstance(exception, dict) and exception.get("exception_type"):
            raise ArmExecutionError(
                f"Harbor trial failed: {exception.get('exception_type')}: {exception.get('exception_message')}"
            )
        patch_path = trial_dir / "agent" / "PATCH.diff"
        patch = patch_path.read_text(encoding="utf-8") if patch_path.is_file() else ""
        return HarborTrialResult(
            trial_dir=trial_dir, agent_metadata=_agent_metadata(payload), patch=patch
        )

    def _script(self, request: HarborTrialRequest) -> str:
        bench = _linux_path(self.bench_root)
        harbor = _linux_path(self.harbor_root)
        task = _linux_path(request.task_dir)
        trials = _linux_path(request.trials_dir)
        exports = "\n".join(
            f"export {name}={shlex.quote(value)}"
            for name, value in sorted(request.controller_env.items())
        )
        install = ""
        if self.install:
            install = (
                f'if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi\n'
                f'"$VENV/bin/python" -m pip install --disable-pip-version-check -U pip setuptools wheel >/dev/null\n'
                f'"$VENV/bin/python" -m pip install --disable-pip-version-check -e {shlex.quote(harbor)} -e {shlex.quote(bench)} >/dev/null\n'
            )
        return (
            "set -euo pipefail\n"
            f"BENCH={shlex.quote(bench)}\n"
            f"VENV={self.venv}\n"
            f"{install}"
            'HARBOR="$VENV/bin/harbor"\n'
            f"rm -rf {shlex.quote(str(request.trials_dir / request.trial_name))}\n"
            "cd $BENCH\n"
            f"{exports}\n"
            f'"$HARBOR" trials start -p {shlex.quote(task)} '
            f"--agent {shlex.quote(request.agent_import_path)} "
            f"--trial-name {shlex.quote(request.trial_name)} "
            f"--trials-dir {shlex.quote(trials)}"
        )

    @staticmethod
    def _default_runner(script: str, timeout: int) -> str:
        if os.name != "nt":
            command = ["bash", "-lc", script]
        else:
            if shutil.which("wsl.exe") is None:
                raise PreDispatchInfrastructureFailure("WSL is not installed; Harbor requires WSL2")
            command = ["wsl.exe", "-e", "bash", "-lc", script]
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            raise ArmExecutionError(
                f"Harbor trial exited {completed.returncode}: {(completed.stdout or '')[-4000:]}"
            )
        return completed.stdout or ""


def _agent_metadata(payload: Mapping[str, object]) -> dict[str, object]:
    agent_result = payload.get("agent_result")
    if not isinstance(agent_result, dict):
        return {}
    metadata = agent_result.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    bench = metadata.get("autonomous_dev_bench")
    return dict(bench) if isinstance(bench, dict) else {}


def _linux_path(path: Path | str) -> str:
    path = Path(path).resolve()
    if os.name != "nt":
        return str(path)
    if shutil.which("wsl.exe") is None:
        raise PreDispatchInfrastructureFailure("WSL is not installed")
    completed = subprocess.run(
        ["wsl.exe", "-e", "wslpath", "-a", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if completed.returncode:
        raise PreDispatchInfrastructureFailure(f"wslpath failed: {completed.stdout}")
    return completed.stdout.strip()


# ---------------------------------------------------------------------------
# Arm executors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArmRuntime:
    """Per-arm wiring: the Harbor agent, the fake-model switch and the model route."""

    arm: ExperimentArm
    agent_import_path: str
    fake_model_env: str
    controller_env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.arm, ExperimentArm):
            object.__setattr__(self, "arm", ExperimentArm(self.arm))

    @property
    def fake_model(self) -> bool:
        return self.controller_env.get(self.fake_model_env) == "1"


class _ArmExecutorBase:
    """One arm of one pair: one Harbor trial, one durable campaign artifact."""

    runtime: ArmRuntime

    def __init__(self, *, runtime: ArmRuntime, launcher: HarborTrialLauncher) -> None:
        self.runtime = runtime
        self.launcher = launcher

    @property
    def arm(self) -> ExperimentArm:
        return self.runtime.arm

    def execute_arm(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        attempt_dir: Path,
    ) -> CampaignArmArtifact:
        if arm is not self.arm:
            raise PreDispatchInfrastructureFailure(
                f"{type(self).__name__} executes {self.arm.value}, not {arm.value}"
            )
        task_dir = self.task_dir(plan)
        manifest = plan.manifest_for(arm)
        attempt_dir = Path(attempt_dir)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        trial = self.launcher.launch(
            HarborTrialRequest(
                task_dir=task_dir,
                agent_import_path=self.runtime.agent_import_path,
                trial_name=manifest.experiment_id,
                trials_dir=attempt_dir / "trials",
                controller_env=dict(self.runtime.controller_env),
                timeout_seconds=manifest.budget.wall_time_seconds + 600,
            )
        )
        model_called = self.model_called(trial)
        tokens, requests = self.accounting(trial, model_called)
        patch_bytes = trial.patch.encode("utf-8")
        evidence = {
            "scope": "PHASE3D_ARM_EXECUTION_EVIDENCE",
            "pair_id": plan.pair_id,
            "arm": arm.value,
            "manifest_identity": str(manifest.identity),
            "status": self.status(trial),
            "model_called": model_called,
            "total_model_tokens": tokens,
            "requests": requests,
            "agent_metadata": dict(trial.agent_metadata),
        }
        evidence_path = attempt_dir / f"evidence-{arm.value}.json"
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (attempt_dir / f"patch-{arm.value}.diff").write_text(trial.patch, encoding="utf-8")
        return CampaignArmArtifact(
            receipt=ArmExecutionReceipt(
                arm=arm,
                manifest_identity=manifest.identity,
                status=self.status(trial),
                model_called=model_called,
                total_model_tokens=tokens,
                requests=requests,
            ),
            patch_sha256="sha256:" + hashlib.sha256(patch_bytes).hexdigest(),
            patch_bytes=len(patch_bytes),
            evidence_sha256="sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        )

    def task_dir(self, plan: PairedExperimentPlan) -> Path:
        raise NotImplementedError

    def model_called(self, trial: HarborTrialResult) -> bool:
        raise NotImplementedError

    def status(self, trial: HarborTrialResult) -> str:
        raise NotImplementedError

    def accounting(self, trial: HarborTrialResult, model_called: bool) -> tuple[int, int]:
        """Exact proxy accounting, or a fail-closed accounting exclusion."""

        if not model_called:
            return 0, 0
        budget = trial.metadata("budget_proxy")
        if not isinstance(budget, Mapping):
            raise ExperimentAccountingUnknownFailure(
                "model-calling arm produced no budget-proxy accounting"
            )
        total = budget.get("total_model_tokens")
        requests = budget.get("requests")
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or isinstance(requests, bool)
            or not isinstance(requests, int)
            or requests < 0
        ):
            raise ExperimentAccountingUnknownFailure("budget-proxy accounting is not exact")
        return total, requests


class StockDeepSeekArmExecutor(_ArmExecutorBase):
    """Execute the shipping stock DeepSeek Harness arm inside Harbor."""

    def __init__(self, *, task_dirs: Mapping[str, Path], launcher: HarborTrialLauncher, controller_env=None) -> None:
        super().__init__(
            runtime=ArmRuntime(
                arm=ExperimentArm.STOCK,
                agent_import_path=STOCK_AGENT,
                fake_model_env=STOCK_FAKE_ENV,
                controller_env=controller_env or {},
            ),
            launcher=launcher,
        )
        self.task_dirs = {str(key): Path(value) for key, value in task_dirs.items()}

    def task_dir(self, plan: PairedExperimentPlan) -> Path:
        task_dir = self.task_dirs.get(plan.task.task_id)
        if task_dir is None:
            raise PreDispatchInfrastructureFailure(
                f"no Harbor task directory registered for {plan.task.task_id}"
            )
        return task_dir

    def model_called(self, trial: HarborTrialResult) -> bool:
        return not self.runtime.fake_model and trial.metadata("fake_model") is not True

    def status(self, trial: HarborTrialResult) -> str:
        return "TASK_LEVEL_FAILURE" if trial.metadata("task_level_failure") else "PATCH_PRODUCED"


class ADCPSemanticsV2ArmExecutor(_ArmExecutorBase):
    """Execute the pinned ADCP runtime arm inside Harbor through the budget proxy."""

    def __init__(self, *, task_dirs: Mapping[str, Path], launcher: HarborTrialLauncher, controller_env=None) -> None:
        super().__init__(
            runtime=ArmRuntime(
                arm=ExperimentArm.ADCP,
                agent_import_path=ADCP_AGENT,
                fake_model_env=ADCP_FAKE_ENV,
                controller_env=controller_env or {},
            ),
            launcher=launcher,
        )
        self.task_dirs = {str(key): Path(value) for key, value in task_dirs.items()}

    def task_dir(self, plan: PairedExperimentPlan) -> Path:
        task_dir = self.task_dirs.get(plan.task.task_id)
        if task_dir is None:
            raise PreDispatchInfrastructureFailure(
                f"no Harbor task directory registered for {plan.task.task_id}"
            )
        return task_dir

    def model_called(self, trial: HarborTrialResult) -> bool:
        return not self.runtime.fake_model and trial.metadata("model_called") is True

    def status(self, trial: HarborTrialResult) -> str:
        outcome = trial.metadata("outcome_status")
        if isinstance(outcome, str) and outcome.strip():
            return outcome
        return "TASK_LEVEL_FAILURE" if trial.metadata("task_level_failure") else "PATCH_PRODUCED"


class BothArmsCampaignExecutor:
    """``CampaignPairExecutor`` that dispatches each arm to its own executor."""

    def __init__(self, stock: StockDeepSeekArmExecutor, adcp: ADCPSemanticsV2ArmExecutor) -> None:
        self._by_arm = {ExperimentArm.STOCK: stock, ExperimentArm.ADCP: adcp}

    def execute_arm(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        attempt_dir: Path,
    ) -> CampaignArmArtifact:
        return self._by_arm[ExperimentArm(arm)].execute_arm(plan, arm, attempt_dir)


# ---------------------------------------------------------------------------
# Official grading
# ---------------------------------------------------------------------------


@runtime_checkable
class OfficialEvaluator(Protocol):
    def evaluate(self, *, instance_id: str, patch: str, run_id: str) -> tuple[OfficialResolution, Sha256Digest]:
        """Score one patch with the pinned official evaluator and return the report digest."""


class LocalOfficialEvaluator:
    """Drive the pinned official ``swebench`` CLI and read its summary verbatim."""

    def __init__(
        self,
        *,
        working_directory: Path,
        executable: str = "swebench",
        workers: int = 1,
        task_repo: Path | None = None,
        runner=None,
    ) -> None:
        self.working_directory = Path(working_directory).resolve()
        self.evaluator = OfficialSwebenchV5(
            executable=executable, workers=workers, task_repo=task_repo
        )
        self._runner = runner or self._default_runner

    def evaluate(self, *, instance_id: str, patch: str, run_id: str) -> tuple[OfficialResolution, Sha256Digest]:
        self.working_directory.mkdir(parents=True, exist_ok=True)
        predictions = self.working_directory / f"{run_id}.predictions.jsonl"
        write_predictions(predictions, [SwebenchPrediction(instance_id, patch, "autobench-arm")])
        self._runner(self.evaluator.prediction_command(run_id, [instance_id], predictions))
        report = self.evaluator.load_results(self.working_directory, run_id)
        return official_outcome(report, instance_id), Sha256Digest.of(report)

    @staticmethod
    def _default_runner(command: tuple[str, ...]) -> None:
        completed = subprocess.run(
            list(command),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=3600,
            check=False,
        )
        if completed.returncode:
            raise ArmExecutionError(
                f"official SWE-bench grading exited {completed.returncode}: {(completed.stdout or '')[-4000:]}"
            )


class CampaignArmGrader:
    """``CampaignOfficialGrader`` over the official evaluator and the arm's patch file."""

    def __init__(self, evaluator: OfficialEvaluator) -> None:
        self.evaluator = evaluator

    def grade_arm(
        self,
        plan: PairedExperimentPlan,
        arm: ExperimentArm,
        artifact: CampaignArmArtifact,
        attempt_dir: Path,
    ) -> OfficialGradeArtifact:
        patch_path = Path(attempt_dir) / f"patch-{ExperimentArm(arm).value}.diff"
        if not patch_path.is_file():
            raise ArmExecutionError(f"arm patch is missing at {patch_path}")
        patch = patch_path.read_text(encoding="utf-8")
        if "sha256:" + hashlib.sha256(patch.encode("utf-8")).hexdigest() != str(artifact.patch_sha256):
            raise ArmExecutionError("arm patch does not match the recorded patch digest")
        run_id = f"{plan.pair_id}-{ExperimentArm(arm).value}"
        resolution, report_digest = self.evaluator.evaluate(
            instance_id=plan.task.task_id, patch=patch, run_id=run_id
        )
        if resolution.resolved is None:
            raise ArmExecutionError(
                f"official grader produced no task verdict ({resolution.outcome}) for {run_id}"
            )
        return OfficialGradeArtifact(resolved=resolution.resolved, evidence_sha256=report_digest)
