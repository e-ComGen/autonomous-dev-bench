"""No-model Harbor agent used only to qualify the execution substrate boundary."""

from __future__ import annotations

import json
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .workspace import HarborWorkspaceFacade


class HarborSubstrateProbeAgent(BaseAgent):
    """Mutate a git workspace, export its patch, and populate Harbor telemetry fields."""

    @staticmethod
    def name() -> str:
        return "autobench-harbor-substrate-probe"

    def __init__(self, logs_dir: Path, model_name: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "SETUP.txt").write_text("setup-called\n", encoding="utf-8")

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        workspace = HarborWorkspaceFacade(environment)
        baseline = await workspace.repository_head()
        await workspace.exec_checked("printf 'harbor substrate qualified\\n' > message.txt")
        status = await workspace.git_status()
        patch = await workspace.git_diff()
        if "message.txt" not in status or not patch.strip():
            raise RuntimeError("Harbor substrate probe produced no observable repository patch")

        (self.logs_dir / "PATCH.diff").write_text(patch, encoding="utf-8")
        evidence = {
            "baseline_commit": baseline,
            "environment_id": getattr(environment, "environment_id", None),
            "instruction_received": bool(instruction.strip()),
            "model_called": False,
            "workspace_status": status.strip().splitlines(),
        }
        (self.logs_dir / "PROBE.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        context.n_input_tokens = 0
        context.n_cache_tokens = 0
        context.n_output_tokens = 0
        context.cost_usd = 0.0
        context.metadata = {"autonomous_dev_bench": evidence}
