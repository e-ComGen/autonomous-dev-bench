"""Native process backend for the SAME issue A/B, without Docker, WSL or system changes."""
from pathlib import Path
from uuid import uuid4
import time
from benchmark_core.execution import ProcessRunner, CommandSpec
from .environment import private_environment
from .environments import NativeEnvironments
from .relay import LocalRelay
from .project import build_native_project


class NativeRuntime:
    backend = "native"

    def __init__(self, root, scratch, settings):
        self.root, self.scratch, self.settings = Path(root).resolve(), Path(scratch).resolve(), settings
        self.runner = ProcessRunner()
        self.environments = NativeEnvironments(self.root)
        self.image = None
        self.network = "local-process-no-network-isolation"
        self.relay = None

    def prepare_image(self):
        self.image = self.environments.prepare_sdk(self.root / "suites/coding/backends/requirements.txt")
        return {"backend": "native", "image_id": self.image, "sdk": "0.1.2rc1", "profile": "sdk",
                "os_isolation": False, "network_isolation": False, "cpu_memory_caps_enforced": False,
                "execution": "EXPLICIT_LOCAL_TRUST", "reboot_required": False,
                "dsh_permission_mode": "danger-full-access", "telemetry_disabled": True}

    def build_project_environment(self, task, policy, deadline):
        return build_native_project(self, task, policy, deadline)

    def validate_environment(self, identity):
        self.environments.load(identity)

    def endpoint(self, token):
        return self.relay.endpoint(token) if self.relay else "http://127.0.0.1:1/no-provider"

    def run(self, directory, *, network="none", entrypoint, timeout, input_path=None, evaluator=None):
        directory = Path(directory).resolve()
        results = directory / "results"
        results.mkdir(exist_ok=True)
        workspace = directory / "workspace"
        deadline = time.monotonic() + timeout
        environment_root = self.scratch / ("env-" + uuid4().hex[:10])
        project_python = self.environments.execution_python(self.image, environment_root, deadline)
        environment = private_environment(directory / "process-home", project_python, workspace)
        environment.update(AUTOBENCH_WORKSPACE=str(workspace), AUTOBENCH_RESULTS=str(results),
            AUTOBENCH_INPUT=str(Path(input_path).resolve()) if input_path else "",
            AUTOBENCH_PROJECT_PYTHON=str(project_python), AUTOBENCH_SCRATCH=str(directory / "process-home/tmp"))
        if "/driver/native_driver.py" in entrypoint:
            # The composition root requires explicit local-execution consent first.
            # Do not pretend that an unavailable native sandbox confines these tools.
            environment.update(DSH_PERMISSION_MODE="danger-full-access", DSH_TELEMETRY_DISABLED="1")
        scripts = {"/driver/native_driver.py": self.root / "suites/coding/native_driver.py",
                   "/evaluator/pytest_process.py": Path(evaluator) / "pytest_process.py" if evaluator else None,
                   "/evaluator/check_process.py": Path(evaluator) / "check_process.py" if evaluator else None}
        args = []
        for item in entrypoint:
            if item in scripts:
                script = scripts[item]
                if script is None or not script.is_file():
                    raise ValueError("Missing declared native entrypoint")
                args.append(str(script.resolve()))
            elif item.startswith("/input/") and input_path:
                args.append(str(Path(input_path).resolve() / Path(item).name))
            elif item == "-I":
                args.append(item)
            else:
                raise ValueError("Unsupported native entrypoint argument")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ARM_TIME_BUDGET_EXHAUSTED")
        execution = self.runner.run(CommandSpec((str(self.environments.sdk_python), *args), remaining,
            str(workspace), environment, inherit_environment=False))
        (directory / "process.log").write_text(execution.stdout[-32768:] + execution.stderr[-32768:], encoding="utf-8")
        return execution

    def start_relay(self, tokens):
        self.relay = LocalRelay(self.root, self.scratch / "relay", self.settings, tokens)
        return self.relay.receipt

    def close(self):
        self.runner.cancel_running()
        if self.relay:
            self.relay.close()
            self.relay = None
