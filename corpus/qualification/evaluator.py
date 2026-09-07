"""Fresh-container test execution on the full repository and protected PR test overlay."""
from pathlib import Path
import json
import shutil
import time
from uuid import uuid4
from .files import materialize, overlay
from .junit import parse_junit, classify


class PytestEvaluator:
    def __init__(self, docker, root, directory, task, image, seconds):
        self.docker, self.root, self.directory = docker, Path(root), Path(directory)
        self.task, self.image, self.seconds = task, image, seconds
        self.deadline = None

    def observe(self, projection, check):
        seconds = min(self.seconds, self.deadline - time.monotonic()) if self.deadline else self.seconds
        if seconds <= 0:
            raise TimeoutError("ARM_TIME_BUDGET_EXHAUSTED")
        directory = self.directory / ("pytest-" + uuid4().hex[:10])
        files = overlay(self.task["base_files"], projection)
        if check["kind"] == "acceptance":
            files.update(self.task["test_overlay"])
        elif check["kind"] != "public":
            raise ValueError("Unknown test surface")
        materialize(directory / "workspace", files)
        inputs, harness = directory / "input", directory / "evaluator"
        inputs.mkdir()
        harness.mkdir()
        (inputs / "checks.json").write_text(json.dumps({"paths": check["paths"], "seconds": max(1, seconds - 2)}))
        shutil.copyfile(self.root / "suites/coding/pytest_process.py", harness / "pytest_process.py")
        previous = self.docker.image
        self.docker.image = self.image
        try:
            execution = self.docker.run(directory, entrypoint=("-I", "/evaluator/pytest_process.py"), timeout=seconds,
                                        input_path=inputs, evaluator=harness)
        finally:
            self.docker.image = previous
        if not execution.succeeded:
            raise RuntimeError("PYTEST_EXECUTION_ERROR")
        result = directory / "results/tests.xml"
        if result.is_symlink() or not result.is_file() or result.stat().st_size > 8388608:
            raise ValueError("INVALID_JUNIT_ARTIFACT")
        return parse_junit(result.read_bytes())

    def score(self, files, checks, expected):
        try:
            observed = self.observe(files, checks)
            status = classify(observed, expected)
            return {"status": status, "cases": len(expected), "observed": observed}
        except (OSError, RuntimeError, ValueError) as error:
            return {"status": "EVALUATION_ERROR", "reason": str(error)[:1000]}
