"""Harbor adapter for the pinned external ADCP runtime.

The benchmark does not reproduce ADCP orchestration. A task image used for the
orchestrated arm stages a small runner at ``/opt/autobench/run_adcp.py``. That
runner owns loading the exact private runtime pin and translating the benchmark
workspace/instruction into the runtime's public contracts. Every model call must
use the shared budget gateway exposed to the task by this adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .adcp_contract import (
    ADCPRuntimeResult,
    ADCP_INTEGRATION,
    ADCP_RUNTIME_COMMIT,
    ADCP_RUNTIME_ENTRYPOINT,
    ADCP_RUNTIME_REPOSITORY,
    SHARED_MODEL_ROUTE,
)
from .workspace import HarborWorkspaceFacade


class ADCPAgent(BaseAgent):
    """Transport-only adapter for the orchestrated benchmark arm."""

    RUNNER = "/opt/autobench/run_adcp.py"
    INSTRUCTION = "/tmp/autobench-adcp-instruction.md"
    RESULT = "/tmp/autobench-adcp-result.json"

    @staticmethod
    def name() -> str:
        return "adcp-pinned-runtime"

    def __init__(self, logs_dir: Path, model_name: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.model_name = model_name or "deepseek-v4-flash"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if not await environment.is_file(self.RUNNER):
            raise RuntimeError(
                "ADCP task image is missing /opt/autobench/run_adcp.py; "
                "the benchmark does not embed the private runtime"
            )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("ADCP instruction must be non-empty")

        gateway_url = os.environ.get("AUTOBENCH_MODEL_GATEWAY_URL", "").strip()
        gateway_token = os.environ.get("AUTOBENCH_MODEL_GATEWAY_TOKEN", "").strip()
        usage_url = os.environ.get("AUTOBENCH_MODEL_GATEWAY_USAGE_URL", "").strip()
        if not gateway_url or not gateway_token or not usage_url:
            raise RuntimeError(
                "ADCP production transport requires AUTOBENCH_MODEL_GATEWAY_URL, "
                "AUTOBENCH_MODEL_GATEWAY_TOKEN and AUTOBENCH_MODEL_GATEWAY_USAGE_URL"
            )

        workspace = HarborWorkspaceFacade(environment)
        await workspace.require_clean_tracked_baseline()
        baseline_head = await workspace.repository_head()
        baseline_untracked = await workspace.untracked_paths()

        local_instruction = self.logs_dir / "INSTRUCTION.md"
        local_result = self.logs_dir / "ADCP_RESULT.json"
        local_instruction.write_text(instruction, encoding="utf-8")
        await environment.upload_file(local_instruction, self.INSTRUCTION)

        runner_env = {
            "AUTOBENCH_MODEL_GATEWAY_URL": gateway_url,
            "AUTOBENCH_MODEL_GATEWAY_TOKEN": gateway_token,
            "AUTOBENCH_MODEL_GATEWAY_USAGE_URL": usage_url,
            "AUTOBENCH_MODEL_ROUTE": SHARED_MODEL_ROUTE,
            "AUTOBENCH_ADCP_RUNTIME_REPOSITORY": ADCP_RUNTIME_REPOSITORY,
            "AUTOBENCH_ADCP_RUNTIME_COMMIT": ADCP_RUNTIME_COMMIT,
            "AUTOBENCH_ADCP_RUNTIME_ENTRYPOINT": ADCP_RUNTIME_ENTRYPOINT,
            "AUTOBENCH_ADCP_INTEGRATION": ADCP_INTEGRATION,
            "AUTOBENCH_ADCP_MODEL": self.model_name,
        }
        command = (
            f"python {shlex.quote(self.RUNNER)} "
            f"--workspace {shlex.quote(workspace.repository_root)} "
            f"--instruction {shlex.quote(self.INSTRUCTION)} "
            f"--result {shlex.quote(self.RESULT)}"
        )
        executed = await environment.exec(
            command,
            cwd=workspace.repository_root,
            env=runner_env,
            timeout_sec=1800,
        )
        if executed.return_code != 0:
            stderr = (executed.stderr or executed.stdout or "")[-4000:]
            raise RuntimeError(f"pinned ADCP runtime runner failed ({executed.return_code}): {stderr}")

        await environment.download_file(self.RESULT, local_result)
        result = ADCPRuntimeResult.from_json_file(local_result)

        final_patch = await workspace.git_diff_since(
            baseline_head,
            baseline_untracked=baseline_untracked,
        )
        if result.outcome == "CANDIDATE_READY" and not final_patch.strip():
            raise RuntimeError("ADCP reported CANDIDATE_READY but produced no workspace delta")
        patch_path = self.logs_dir / "PATCH.diff"
        patch_path.write_text(final_patch, encoding="utf-8")

        accounting = result.model_accounting
        context.n_input_tokens = accounting.input_tokens
        context.n_output_tokens = accounting.output_tokens
        context.n_cache_tokens = accounting.cache_tokens
        context.cost_usd = accounting.cost_usd_micros / 1_000_000
        context.metadata = {
            "autonomous_dev_bench": {
                "agent": self.name(),
                "model": self.model_name,
                "model_route": SHARED_MODEL_ROUTE,
                "direct_model_api_used": False,
                "runtime_repository": ADCP_RUNTIME_REPOSITORY,
                "runtime_commit": ADCP_RUNTIME_COMMIT,
                "runtime_entrypoint": ADCP_RUNTIME_ENTRYPOINT,
                "runtime_integration": ADCP_INTEGRATION,
                "adcp_outcome": result.outcome,
                "adcp_role_calls": result.role_calls,
                "adcp_roles_seen": list(result.roles_seen),
                "adcp_evidence": list(result.evidence),
                "model_requests": accounting.requests,
                "reasoning_tokens": accounting.reasoning_tokens,
                "model_accounting_valid": accounting.accounting_valid,
                "model_budget_violations": list(accounting.violations),
                "baseline_head": baseline_head,
                "baseline_untracked_count": len(baseline_untracked),
                "final_head": await workspace.repository_head(),
                "patch_sha256": hashlib.sha256(final_patch.encode("utf-8")).hexdigest(),
                "patch_bytes": len(final_patch.encode("utf-8")),
                "runtime_metadata": dict(result.metadata),
            }
        }
