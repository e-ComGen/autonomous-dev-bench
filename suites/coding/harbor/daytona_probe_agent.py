"""Daytona-specific no-model Harbor remote-provider qualification agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .probe_agent import HarborSubstrateProbeAgent, _record_context
from .workspace import HarborWorkspaceFacade


class HarborDaytonaRemoteProbeAgent(HarborSubstrateProbeAgent):
    """Prove the generic substrate contract is executing in a real Daytona sandbox."""

    @staticmethod
    def name() -> str:
        return "autobench-harbor-daytona-remote-probe"

    def version(self) -> str:
        return "1.0.0"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await super().run(instruction, environment, context)
        workspace = HarborWorkspaceFacade(environment)

        env_type_obj = environment.type()
        env_type = getattr(env_type_obj, "value", str(env_type_obj))
        if env_type != "daytona":
            raise RuntimeError(f"remote provider probe expected Daytona, observed {env_type!r}")

        sandbox_id = (await workspace.exec_checked("cat /harbor/daytona_sandbox_id")).strip()
        if not sandbox_id:
            raise RuntimeError("Daytona did not expose a non-empty sandbox id")

        os_name = (await workspace.exec_checked("uname -s")).strip()
        architecture = (await workspace.exec_checked("uname -m")).strip()
        if os_name != "Linux":
            raise RuntimeError(f"Daytona qualification expected Linux, observed {os_name!r}")

        probe_path = self.logs_dir / "PROBE.json"
        evidence = json.loads(probe_path.read_text(encoding="utf-8"))
        evidence.update(
            {
                "remote_provider": "daytona",
                "environment_type": env_type,
                "environment_class": (
                    f"{environment.__class__.__module__}.{environment.__class__.__qualname__}"
                ),
                "sandbox_id_present": True,
                "sandbox_id_sha256": hashlib.sha256(sandbox_id.encode("utf-8")).hexdigest(),
                "os": os_name,
                "architecture": architecture,
            }
        )
        probe_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _record_context(context, evidence)
