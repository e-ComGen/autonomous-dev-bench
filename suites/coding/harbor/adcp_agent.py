"""Harbor adapter for the pinned external ADCP runtime.

The benchmark does not reproduce ADCP orchestration. A task image used for the
orchestrated arm stages a small runner at ``/opt/autobench/run_adcp.py``. That
runner owns loading the exact private runtime pin and translating the benchmark
workspace/instruction into the runtime's public contracts. Every model call must
use the shared budget gateway exposed to the task by this adapter.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import tempfile

from harbor.agents.base import BaseAgent, BaseAgentContext

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
        return "adcp_pinned_runtime"

    async def setup(self, environment) -> None:
        result = await environment.exec(f"test -f {shlex.quote(self.RUNNER)}")
        if result.return_code != 0:
            raise RuntimeError(
                "ADCP task image is missing /opt/autobench/run_adcp.py; "
                "the benchmark does not embed the private runtime"
            )

    async def run(self, instruction: str, environment, context: BaseAgentContext) -> None:
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("ADCP instruction must be non-empty")

        gateway_url = os.environ.get("AUTOBENCH_MODEL_GATEWAY_URL", "").strip()
        gateway_token = os.environ.get("AUTOBENCH_MODEL_GATEWAY_TOKEN", "").strip()
        if not gateway_url or not gateway_token:
            raise RuntimeError(
                "ADCP production transport requires AUTOBENCH_MODEL_GATEWAY_URL "
                "and AUTOBENCH_MODEL_GATEWAY_TOKEN"
            )
        if os.environ.get("AUTOBENCH_DEEPSEEK_API_KEY"):
            raise RuntimeError("raw upstream model credentials must not enter the ADCP task boundary")

        workspace = HarborWorkspaceFacade(environment)
        await workspace.require_clean_tracked_baseline()
        baseline_head = await workspace.repository_head()
        baseline_untracked = await workspace.untracked_paths()

        with tempfile.TemporaryDirectory(prefix="autobench-adcp-") as temporary:
            root = Path(temporary)
            local_instruction = root / "instruction.md"
            local_result = root / "result.json"
            local_instruction.write_text(instruction, encoding="utf-8")
            await environment.upload_file(local_instruction, self.INSTRUCTION)

            env = {
                "AUTOBENCH_MODEL_GATEWAY_URL": gateway_url,
                "AUTOBENCH_MODEL_GATEWAY_TOKEN": gateway_token,
                "AUTOBENCH_MODEL_ROUTE": SHARED_MODEL_ROUTE,
                "AUTOBENCH_ADCP_RUNTIME_REPOSITORY": ADCP_RUNTIME_REPOSITORY,
                "AUTOBENCH_ADCP_RUNTIME_COMMIT": ADCP_RUNTIME_COMMIT,
                "AUTOBENCH_ADCP_RUNTIME_ENTRYPOINT": ADCP_RUNTIME_ENTRYPOINT,
                "AUTOBENCH_ADCP_INTEGRATION": ADCP_INTEGRATION,
            }
            prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
            command = (
                f"env {prefix} python {shlex.quote(self.RUNNER)} "
                f"--workspace {shlex.quote(workspace.repository_root)} "
                f"--instruction {shlex.quote(self.INSTRUCTION)} "
                f"--result {shlex.quote(self.RESULT)}"
            )
            executed = await environment.exec(command, cwd=workspace.repository_root)
            if executed.return_code != 0:
                stderr = (executed.stderr or "")[-4000:]
                raise RuntimeError(f"pinned ADCP runtime runner failed ({executed.return_code}): {stderr}")

            await environment.download_file(self.RESULT, local_result)
            result = ADCPRuntimeResult.from_json_file(local_result)

        final_patch = await workspace.git_diff_since(
            baseline_head,
            baseline_untracked=baseline_untracked,
        )
        if result.outcome == "CANDIDATE_READY" and not final_patch.strip():
            raise RuntimeError("ADCP reported CANDIDATE_READY but produced no workspace delta")

        accounting = result.model_accounting
        context.add_input_tokens(accounting.input_tokens)
        context.add_output_tokens(accounting.output_tokens)
        context.add_auxiliary_tokens(accounting.reasoning_tokens)
        context.add_cache_tokens(accounting.cache_tokens)
        context.add_cost(accounting.cost_usd_micros / 1_000_000)
        context.set_metadata("agent", self.name())
        context.set_metadata("model_route", SHARED_MODEL_ROUTE)
        context.set_metadata("runtime_repository", ADCP_RUNTIME_REPOSITORY)
        context.set_metadata("runtime_commit", ADCP_RUNTIME_COMMIT)
        context.set_metadata("runtime_entrypoint", ADCP_RUNTIME_ENTRYPOINT)
        context.set_metadata("runtime_integration", ADCP_INTEGRATION)
        context.set_metadata("adcp_outcome", result.outcome)
        context.set_metadata("adcp_role_calls", result.role_calls)
        context.set_metadata("adcp_roles_seen", json.dumps(result.roles_seen))
        context.set_metadata("model_requests", accounting.requests)
        context.set_metadata("model_accounting_valid", accounting.accounting_valid)
        context.set_metadata("model_budget_violations", json.dumps(accounting.violations))
        context.set_metadata("baseline_head", baseline_head)
        context.set_metadata("final_head", await workspace.repository_head())
        context.set_metadata("final_patch_bytes", len(final_patch.encode("utf-8")))
        context.set_metadata("final_patch", final_patch)
