"""Harbor adapter that preserves the stock DeepSeek Harness as the coding agent."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .workspace import HarborWorkspaceFacade


class StockDeepSeekAgent(BaseAgent):
    """Run the pinned DeepSeek Harness runtime inside the Harbor task workspace."""

    RUNNER_PATH = "/opt/autobench/run_stock_deepseek.py"
    PROMPT_PATH = "/tmp/autobench-stock-instruction.md"
    RESULT_PATH = "/tmp/autobench-stock-result.json"
    EXPECTED_VERSION = "0.1.2rc1"

    @staticmethod
    def name() -> str:
        return "stock-deepseek-harness"

    def __init__(self, logs_dir: Path, model_name: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.model_name = model_name or "deepseek-v4-flash"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if not await environment.is_file(self.RUNNER_PATH):
            raise FileNotFoundError(f"stock DeepSeek runner missing from task image: {self.RUNNER_PATH}")

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        base_url = os.environ.get("AUTOBENCH_DEEPSEEK_BASE_URL")
        api_key = os.environ.get("AUTOBENCH_DEEPSEEK_API_KEY")
        if not base_url or not api_key:
            raise ValueError("StockDeepSeekAgent requires controller-side DeepSeek route credentials")

        prompt_file = self.logs_dir / "INSTRUCTION.md"
        prompt_file.write_text(instruction, encoding="utf-8")
        await environment.upload_file(prompt_file, self.PROMPT_PATH)

        workspace = HarborWorkspaceFacade(environment)
        baseline_commit = await workspace.repository_head()
        runner_env = {
            "DEEPSEEK_BASE_URL": base_url,
            "DEEPSEEK_API_KEY": api_key,
            "AUTOBENCH_DSH_PROMPT_PATH": self.PROMPT_PATH,
            "AUTOBENCH_DSH_RESULT_PATH": self.RESULT_PATH,
            "AUTOBENCH_DSH_WORKSPACE": workspace.repository_root,
            "AUTOBENCH_DSH_PROFILE": "sdk",
            "AUTOBENCH_DSH_PROVIDER": "deepseek-official",
            "AUTOBENCH_DSH_MODEL": self.model_name,
            "AUTOBENCH_DSH_SESSION_ID": f"harbor-{self.logs_dir.parent.name}",
        }
        usage_url = os.environ.get("AUTOBENCH_DEEPSEEK_USAGE_URL")
        if usage_url:
            runner_env["AUTOBENCH_DEEPSEEK_USAGE_URL"] = usage_url
        if os.environ.get("AUTOBENCH_FAKE_MODEL") == "1":
            runner_env["AUTOBENCH_FAKE_MODEL"] = "1"

        execution = await environment.exec(
            f"python {self.RUNNER_PATH}",
            cwd=workspace.repository_root,
            env=runner_env,
            timeout_sec=120,
        )
        if execution.return_code != 0:
            stderr = (execution.stderr or execution.stdout or "")[-4000:]
            raise RuntimeError(f"stock DeepSeek Harness runner failed ({execution.return_code}): {stderr}")

        local_result = self.logs_dir / "DSH_RESULT.json"
        await environment.download_file(self.RESULT_PATH, local_result)
        result = json.loads(local_result.read_text(encoding="utf-8"))
        if result.get("sdk_version") != self.EXPECTED_VERSION or result.get("runtime_version") != self.EXPECTED_VERSION:
            raise ValueError(f"stock DeepSeek Harness version mismatch: {result}")
        if result.get("profile") != "sdk" or result.get("provider") != "deepseek-official":
            raise ValueError("stock DeepSeek Harness composition changed")
        if result.get("model") != self.model_name:
            raise ValueError("stock DeepSeek model identity changed")

        patch = await workspace.git_diff()
        if not patch.strip():
            raise ValueError("stock DeepSeek Harness produced no repository patch")
        patch_path = self.logs_dir / "PATCH.diff"
        patch_path.write_text(patch, encoding="utf-8")

        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        cache_tokens = usage.get("cache_tokens", 0)
        context.n_input_tokens = prompt_tokens if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) else None
        context.n_output_tokens = completion_tokens if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool) else None
        context.n_cache_tokens = cache_tokens if isinstance(cache_tokens, int) and not isinstance(cache_tokens, bool) else None
        context.cost_usd = 0.0 if result.get("fake_model") is True else None
        context.metadata = {
            "autonomous_dev_bench": {
                "agent": "stock_deepseek_harness",
                "baseline_commit": baseline_commit,
                "environment_id": getattr(environment, "environment_id", None),
                "profile": result["profile"],
                "provider": result["provider"],
                "model": result["model"],
                "sdk_version": result["sdk_version"],
                "runtime_version": result["runtime_version"],
                "runtime_path": result.get("runtime_path"),
                "finish_reason": result.get("finish_reason"),
                "final_response": result.get("final_response"),
                "event_count": result.get("event_count"),
                "fake_model": result.get("fake_model") is True,
                "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                "patch_bytes": len(patch.encode("utf-8")),
            }
        }
