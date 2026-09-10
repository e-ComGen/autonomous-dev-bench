"""Harbor adapter for the externally supplied pinned ADCP runner."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen
from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from suites.coding.adcp_contract import ADCP_COMMIT, ADCP_INTEGRATION, ADCP_MODEL_ROUTE, ADCP_REPOSITORY, ADCP_RUNTIME, parse_adcp_runner_receipt
from .workspace import HarborWorkspaceFacade


class ADCPHarborAgent(BaseAgent):
    RUNNER_PATH = "/opt/autobench/run_adcp.py"
    PYTHON_PATH = "/opt/autobench/python312/bin/python3.12"
    INSTRUCTION_PATH = "/tmp/autobench-adcp-instruction.md"
    RESULT_PATH = "/tmp/autobench-adcp-result.json"

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
        for path in (self.RUNNER_PATH, self.PYTHON_PATH):
            if not await environment.is_file(path):
                raise FileNotFoundError(f"ADCP runtime dependency missing from task image: {path}")

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        proxy_base_url = self._required_env("AUTOBENCH_MODEL_PROXY_BASE_URL")
        proxy_token = self._required_env("AUTOBENCH_MODEL_PROXY_TOKEN")
        fake_runtime = os.environ.get("AUTOBENCH_ADCP_FAKE_RUNTIME") == "1"
        instruction_file = self.logs_dir / "INSTRUCTION.md"
        instruction_file.write_text(instruction, encoding="utf-8")
        await environment.upload_file(instruction_file, self.INSTRUCTION_PATH)
        workspace = HarborWorkspaceFacade(environment)
        baseline_commit = await workspace.repository_head()
        await workspace.require_clean_tracked_baseline()
        baseline_untracked = await workspace.untracked_paths()
        credential_probe = await environment.exec("test -z \"${AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY:-}\"", cwd=workspace.repository_root)
        if credential_probe.return_code != 0:
            raise RuntimeError("task environment exposes an upstream provider credential")
        runner_env = {
            "AUTOBENCH_ADCP_INSTRUCTION_PATH": self.INSTRUCTION_PATH,
            "AUTOBENCH_ADCP_RESULT_PATH": self.RESULT_PATH,
            "AUTOBENCH_ADCP_WORKSPACE": workspace.repository_root,
            "AUTOBENCH_ADCP_STATE_ROOT": "/tmp/autobench-adcp-state",
            "AUTOBENCH_ADCP_ROOT": "/opt/autobench/adcp",
            "AUTOBENCH_ADCP_TARGET_REPOSITORY": ADCP_REPOSITORY,
            "AUTOBENCH_ADCP_TARGET_COMMIT": ADCP_COMMIT,
            "AUTOBENCH_ADCP_TARGET_RUNTIME": ADCP_RUNTIME,
            "AUTOBENCH_ADCP_TARGET_INTEGRATION": ADCP_INTEGRATION,
            "AUTOBENCH_ADCP_MODEL": self.model_name,
            "AUTOBENCH_ADCP_PROVIDER": "deepseek-official",
            "AUTOBENCH_ADCP_MAX_TOKENS_PER_REQUEST": "16384",
            "AUTOBENCH_MODEL_PROXY_MODE": "1",
            "DEEPSEEK_BASE_URL": proxy_base_url,
            "DEEPSEEK_API_KEY": proxy_token,
        }
        if fake_runtime:
            runner_env["AUTOBENCH_ADCP_FAKE_RUNTIME"] = "1"
        execution = await environment.exec(f"{self.PYTHON_PATH} {self.RUNNER_PATH}", cwd=workspace.repository_root, env=runner_env, timeout_sec=600)
        if execution.return_code != 0:
            diagnostic = (execution.stderr or execution.stdout or "")[-5000:]
            raise RuntimeError(f"external ADCP runner failed ({execution.return_code}): {diagnostic}")
        local_result = self.logs_dir / "ADCP_RESULT.json"
        await environment.download_file(self.RESULT_PATH, local_result)
        raw = json.loads(local_result.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("external ADCP runner returned a non-object receipt")
        receipt = parse_adcp_runner_receipt(raw, allow_fake_runtime=fake_runtime, require_repair_cycle=fake_runtime, allow_nonready_terminal=not fake_runtime)
        patch = await workspace.git_diff(baseline_untracked=baseline_untracked)
        patch_path = self.logs_dir / "PATCH.diff"
        patch_path.write_text(patch, encoding="utf-8")
        usage = self._usage_snapshot(receipt.model_called)
        context.n_input_tokens = usage["input_tokens"]
        context.n_output_tokens = usage["output_tokens"]
        context.n_cache_tokens = usage["cache_tokens"]
        context.cost_usd = usage["cost_usd"]
        context.metadata = {"autonomous_dev_bench": {
            "agent": "adcp", "baseline_commit": baseline_commit,
            "environment_id": getattr(environment, "environment_id", None),
            "target_runtime": {"repository": receipt.target_runtime.repository, "commit": receipt.target_runtime.commit, "runtime": receipt.target_runtime.runtime, "integration": receipt.target_runtime.integration},
            "runtime_loaded": receipt.runtime_loaded, "fake_runtime": receipt.fake_runtime,
            "role_ids": dict(receipt.role_ids), "role_call_counts": dict(receipt.role_call_counts),
            "event_sequence": list(receipt.event_sequence), "outcome_status": receipt.outcome_status,
            "candidate_ready": receipt.candidate_ready, "task_completed": receipt.task_completed,
            "repair_count": receipt.repair_count, "session_id": receipt.session_id,
            "request_id": receipt.request_id, "candidate_snapshot_id": receipt.candidate_snapshot_id,
            "model": receipt.model_route, "provider": receipt.provider_route, "model_called": receipt.model_called,
            "model_calls_via_budget_proxy": receipt.model_calls_via_budget_proxy,
            "upstream_provider_credential_present": receipt.upstream_provider_credential_present,
            "proxy_credential_present": receipt.proxy_credential_present,
            "max_tokens_per_request": 16384, "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            "patch_bytes": len(patch.encode("utf-8")), "empty_patch": not patch.strip(), "budget_proxy": usage,
        }}

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
