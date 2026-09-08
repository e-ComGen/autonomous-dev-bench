"""No-model Harbor agent used only to prove official SWE-bench final re-grade transport."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .workspace import HarborWorkspaceFacade


class HarborOfficialRegradeProbeAgent(BaseAgent):
    """Create a harmless repository patch without accessing benchmark answer material."""

    REPOSITORY_ROOT = "/testbed"
    MARKER = "AUTOBENCH_TRANSPORT_PROBE.txt"
    CONTENT = "harbor official regrade transport probe\n"

    @staticmethod
    def name() -> str:
        return "autobench-harbor-official-regrade-probe"

    def __init__(self, logs_dir: Path, model_name: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        workspace = HarborWorkspaceFacade(environment, self.REPOSITORY_ROOT)
        baseline_commit = await workspace.repository_head()
        await workspace.exec_checked(
            f"printf 'harbor official regrade transport probe\\n' > {self.MARKER}",
            cwd=self.REPOSITORY_ROOT,
        )
        patch = await workspace.git_diff()
        if self.MARKER not in patch or "+harbor official regrade transport probe" not in patch:
            raise ValueError("Harbor official re-grade probe patch was not exported")
        patch_path = self.logs_dir / "PATCH.diff"
        patch_path.write_text(patch, encoding="utf-8")
        evidence = {
            "model_called": False,
            "instruction_received": bool(instruction.strip()),
            "baseline_commit": baseline_commit,
            "environment_id": getattr(environment, "environment_id", None),
            "repository_root": self.REPOSITORY_ROOT,
            "marker": self.MARKER,
            "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            "patch_bytes": len(patch.encode("utf-8")),
        }
        (self.logs_dir / "OFFICIAL_REGRADE_PROBE.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        context.n_input_tokens = 0
        context.n_cache_tokens = 0
        context.n_output_tokens = 0
        context.cost_usd = 0.0
        context.metadata = {"autonomous_dev_bench": evidence}
