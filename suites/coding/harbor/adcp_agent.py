"""Harbor adapter for the pinned controller-side ADCP runtime.

The SWE-bench task image remains the canonical project environment. ADCP executes
under the benchmark controller's pinned Python, against an exact tarred clone of
the task Git workspace, then its resulting Git diff is applied back to the task
workspace. The real provider credential never enters either workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from suites.coding.adcp_contract import ADCP_COMMIT, ADCP_INTEGRATION, ADCP_MODEL_ROUTE, ADCP_REPOSITORY, ADCP_RUNTIME, parse_adcp_runner_receipt
from .workspace import HarborWorkspaceFacade


class ADCPHarborAgent(BaseAgent):
    SNAPSHOT_PATH = "/tmp/autobench-adcp-workspace.tar.gz"
    APPLY_PATCH_PATH = "/tmp/autobench-adcp.patch"

    @staticmethod
    def name() -> str:
        return "autobench-adcp-harbor"

    def __init__(self, logs_dir: Path, model_name: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.model_name = model_name or ADCP_MODEL_ROUTE

    def version(self) -> str:
        return "2.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        adcp_root = self._required_env("AUTOBENCH_ADCP_ROOT")
        observed = self._git(Path(adcp_root), "rev-parse", "HEAD")
        if observed != ADCP_COMMIT:
            raise ValueError(f"ADCP checkout mismatch: expected {ADCP_COMMIT}, got {observed}")

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        proxy_base_url = self._required_env("AUTOBENCH_MODEL_PROXY_BASE_URL")
        proxy_token = self._required_env("AUTOBENCH_MODEL_PROXY_TOKEN")
        adcp_root = Path(self._required_env("AUTOBENCH_ADCP_ROOT")).resolve()
        if os.environ.get("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY"):
            raise RuntimeError("controller agent environment exposes the upstream provider credential")

        workspace = HarborWorkspaceFacade(environment)
        baseline_commit = await workspace.repository_head()
        await workspace.require_clean_tracked_baseline()
        baseline_untracked = await workspace.untracked_paths()

        tar_result = await environment.exec(
            f"tar -C {workspace.repository_root} -czf {self.SNAPSHOT_PATH} .",
            cwd=workspace.repository_root,
            timeout_sec=120,
        )
        if tar_result.return_code != 0:
            raise RuntimeError("could not snapshot task workspace: " + (tar_result.stderr or tar_result.stdout or "")[-3000:])

        instruction_path = self.logs_dir / "INSTRUCTION.md"
        instruction_path.write_text(instruction, encoding="utf-8")
        local_archive = self.logs_dir / "workspace.tar.gz"
        await environment.download_file(self.SNAPSHOT_PATH, local_archive)

        with tempfile.TemporaryDirectory(prefix="autobench-adcp-task-") as temporary:
            local_workspace = Path(temporary) / "workspace"
            local_workspace.mkdir()
            with tarfile.open(local_archive, "r:gz") as archive:
                archive.extractall(local_workspace, filter="data")
            if self._git(local_workspace, "rev-parse", "HEAD") != baseline_commit:
                raise RuntimeError("downloaded task snapshot changed baseline commit")

            result_path = Path(temporary) / "ADCP_RESULT.json"
            state_root = Path(temporary) / "state"
            env = os.environ.copy()
            # Runner receives only the experiment proxy credential. The upstream
            # key stays inside the host-side budget proxy process.
            env.pop("DEEPSEEK_API_KEY", None)
            env.pop("AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY", None)
            env.update({
                "AUTOBENCH_ADCP_ROOT": str(adcp_root),
                "AUTOBENCH_ADCP_INSTRUCTION_PATH": str(instruction_path),
                "AUTOBENCH_ADCP_RESULT_PATH": str(result_path),
                "AUTOBENCH_ADCP_WORKSPACE": str(local_workspace),
                "AUTOBENCH_ADCP_STATE_ROOT": str(state_root),
                "AUTOBENCH_ADCP_TARGET_REPOSITORY": ADCP_REPOSITORY,
                "AUTOBENCH_ADCP_TARGET_COMMIT": ADCP_COMMIT,
                "AUTOBENCH_ADCP_TARGET_RUNTIME": ADCP_RUNTIME,
                "AUTOBENCH_ADCP_TARGET_INTEGRATION": ADCP_INTEGRATION,
                "AUTOBENCH_ADCP_MODEL": self.model_name,
                "AUTOBENCH_ADCP_PROVIDER": "deepseek-official",
                "AUTOBENCH_MODEL_PROXY_MODE": "1",
                "DEEPSEEK_BASE_URL": proxy_base_url,
                "DEEPSEEK_API_KEY": proxy_token,
            })
            runner = Path(__file__).with_name("adcp_swebench_runner.py")
            completed = subprocess.run(
                [sys.executable, str(runner)],
                cwd=Path(__file__).resolve().parents[3], env=env,
                text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=600, check=False,
            )
            if completed.stdout:
                (self.logs_dir / "ADCP_RUNNER.log").write_text(completed.stdout, encoding="utf-8")
            if completed.returncode != 0 or not result_path.is_file():
                raise RuntimeError(f"controller-side ADCP runner failed ({completed.returncode}): {(completed.stdout or '')[-5000:]}")

            raw = json.loads(result_path.read_text(encoding="utf-8"))
            receipt = parse_adcp_runner_receipt(raw, allow_nonready_terminal=True)
            patch = subprocess.run(
                ["git", "-C", str(local_workspace), "diff", "--binary", "--no-ext-diff", f"{baseline_commit}..HEAD", "--"],
                text=True, encoding="utf-8", errors="strict", capture_output=True,
                timeout=60, check=True,
            ).stdout

        patch_bytes = len(patch.encode("utf-8"))
        if patch_bytes > 262144:
            raise RuntimeError(f"ADCP patch exceeds preregistered cap: {patch_bytes}")
        patch_path = self.logs_dir / "PATCH.diff"
        patch_path.write_text(patch, encoding="utf-8")
        if patch:
            await environment.upload_file(patch_path, self.APPLY_PATCH_PATH)
            applied = await environment.exec(
                f"git apply --binary --whitespace=nowarn {self.APPLY_PATCH_PATH}",
                cwd=workspace.repository_root,
                timeout_sec=120,
            )
            if applied.return_code != 0:
                raise RuntimeError("ADCP patch could not be applied to exact task baseline: " + (applied.stderr or applied.stdout or "")[-3000:])

        observed_patch = await workspace.git_diff(baseline_untracked=baseline_untracked)
        if observed_patch != patch:
            raise RuntimeError("task workspace diff differs from controller-side ADCP patch")

        usage = self._usage_snapshot(receipt.model_called)
        context.n_input_tokens = usage["input_tokens"]
        context.n_output_tokens = usage["output_tokens"]
        context.n_cache_tokens = usage["cache_tokens"]
        context.cost_usd = usage["cost_usd"]
        context.metadata = {
            "autonomous_dev_bench": {
                "agent": "adcp",
                "baseline_commit": baseline_commit,
                "environment_id": getattr(environment, "environment_id", None),
                "controller_python": sys.version.split()[0],
                "target_runtime": {
                    "repository": receipt.target_runtime.repository,
                    "commit": receipt.target_runtime.commit,
                    "runtime": receipt.target_runtime.runtime,
                    "integration": receipt.target_runtime.integration,
                },
                "runtime_loaded": receipt.runtime_loaded,
                "role_ids": dict(receipt.role_ids),
                "role_call_counts": dict(receipt.role_call_counts),
                "event_sequence": list(receipt.event_sequence),
                "outcome_status": receipt.outcome_status,
                "candidate_ready": receipt.candidate_ready,
                "task_completed": receipt.task_completed,
                "repair_count": receipt.repair_count,
                "session_id": receipt.session_id,
                "request_id": receipt.request_id,
                "candidate_snapshot_id": receipt.candidate_snapshot_id,
                "model": receipt.model_route,
                "provider": receipt.provider_route,
                "model_called": receipt.model_called,
                "model_calls_via_budget_proxy": receipt.model_calls_via_budget_proxy,
                "upstream_provider_credential_present": receipt.upstream_provider_credential_present,
                "proxy_credential_present": receipt.proxy_credential_present,
                "max_tokens_per_request": 16384,
                "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                "patch_bytes": patch_bytes,
                "empty_patch": not patch.strip(),
                "budget_proxy": usage,
            }
        }

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        completed = subprocess.run(["git", "-C", str(root), *args], text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr[-2000:])
        return completed.stdout.strip()

    @staticmethod
    def _required_env(name: str) -> str:
        value = os.environ.get(name)
        if value is None or not value.strip():
            raise ValueError(f"ADCPHarborAgent requires controller-side {name}")
        return value

    @staticmethod
    def _usage_snapshot(model_called: bool) -> dict[str, int | float | bool]:
        if not model_called:
            return {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "total_model_tokens": 0, "requests": 0, "cost_usd": 0.0, "accounting_unknown": False}
        url = os.environ.get("AUTOBENCH_MODEL_PROXY_USAGE_URL")
        if not url:
            raise ValueError("model-calling ADCP run requires AUTOBENCH_MODEL_PROXY_USAGE_URL")
        with urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("budget"), dict):
            raise ValueError("budget proxy usage endpoint returned an invalid object")
        if payload.get("accounting_unknown") is not False:
            raise ValueError("budget proxy accounting is unknown")
        budget = payload["budget"]
        if budget.get("open_reservations") != 0:
            raise ValueError("budget proxy still has open model-call reservations")
        result: dict[str, int | float | bool] = {"accounting_unknown": False}
        for name in ("input_tokens", "output_tokens", "cache_tokens", "total_model_tokens", "requests"):
            value = budget.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"budget proxy usage has invalid {name}")
            result[name] = value
        cost = budget.get("cost_usd", 0.0)
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            raise ValueError("budget proxy usage has invalid cost_usd")
        result["cost_usd"] = float(cost)
        return result
