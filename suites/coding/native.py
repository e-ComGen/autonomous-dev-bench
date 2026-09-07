"""One actual native driver shared by the stock arm and ADCP semantic roles."""
from pathlib import Path
import json
import time
from uuid import uuid4
from .evaluation import read_json
from .source import write_files, snapshot_files


class NativeDriver:
    def __init__(self, docker, directory, settings, token, deadline=None, workspace_adapter=None):
        self.docker, self.directory, self.settings = docker, Path(directory), settings
        self.token = token
        self.deadline = deadline or time.monotonic() + settings.arm_seconds
        self.workspace_adapter = workspace_adapter
        self.invocations = []
        self.last_candidate = None

    def invoke(self, files, prompt, *, boot_only=False):
        remaining = self.deadline - time.monotonic()
        if remaining < 1:
            raise TimeoutError("ARM_TIME_BUDGET_EXHAUSTED")
        directory = self.directory / ("native-" + uuid4().hex[:10])
        if self.workspace_adapter:
            self.workspace_adapter.materialize(files, directory / "workspace")
        else:
            write_files(directory / "workspace", files)
        inputs = directory / "input"
        inputs.mkdir()
        request = {"model": self.settings.model, "max_tokens": self.settings.output_tokens_per_request,
                   "endpoint": f"http://model-relay:8787/{self.token}", "timeout": remaining,
                   "session_id": "bench-" + uuid4().hex, "prompt": prompt, "boot_only": boot_only}
        (inputs / "request.json").write_text(json.dumps(request), encoding="utf-8")
        execution = self.docker.run(directory, network=self.docker.network if not boot_only else "none",
                                    entrypoint=("-I", "/driver/native_driver.py"), timeout=remaining, input_path=inputs)
        self.invocations.append({"session_id": request["session_id"], "returncode": execution.returncode,
                                 "timed_out": execution.timed_out, "wall_seconds": execution.wall_time_seconds})
        if not execution.succeeded:
            raise RuntimeError("NATIVE_DSH_FAILED: " + str(directory / "process.log"))
        returned = read_json(directory / "results/native.json")
        if boot_only:
            if returned != {"status": "BOOTED", "model_called": False}:
                raise ValueError("Native SDK boot gate did not complete")
            return returned, files
        if returned.get("status") != "RETURNED" or not isinstance(returned.get("text"), str):
            raise ValueError("Native SDK returned no valid response")
        if self.workspace_adapter:
            after = self.workspace_adapter.read_candidate(files, directory / "workspace")
        else:
            after = snapshot_files(directory / "workspace")
            allowed = {path for path in files if path.endswith(".py") and path != "public_tests.py"}
            changed = {path for path in set(files) | set(after) if files.get(path) != after.get(path)}
            if changed - allowed:
                raise ValueError("Native candidate changed protected or undeclared files")
            if sum(len(after.get(path, "").encode()) for path in changed) > self.settings.max_patch_bytes:
                raise ValueError("Native candidate exceeded the common patch size limit")
        self.last_candidate = after
        return returned, after


def stock_arm(driver, files, objective):
    result, candidate = driver.invoke(files,
        objective + "\nWork in /workspace. Inspect and edit the project using your normal tools. "
        "Run python -B public_tests.py as appropriate. Do not change tests, configuration, TASK.md or public_tests.py. "
        "Deliver the implementation, not just a proposed patch in your final message.")
    return candidate, {"status": "RETURNED" if result.get("finish_reason") == "completed" else "NATIVE_INCOMPLETE",
                       "finish_reason": result.get("finish_reason"),
                       "driver": "DeepSeekHarness(profile=sdk)", "invocations": driver.invocations}
