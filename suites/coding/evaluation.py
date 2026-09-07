"""External, source-bound functional checks; no hidden feedback reaches a role."""
from pathlib import Path
import json
import shutil
from uuid import uuid4

from .recipes import RECIPES
from .source import write_files, omit_function


def read_json(path, limit=262144):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Missing or unsafe bounded result file")
    return json.loads(path.read_text(encoding="utf-8"))


def checks_for(recipe):
    return [{"id": f"{other.task_id}:{number}", "module": other.module,
             "symbol": other.symbol, "case": case}
            for other in RECIPES if other.project_id == recipe.project_id
            for number, case in enumerate(other.cases)]


class Evaluator:
    def __init__(self, docker, root, directory, seconds):
        self.docker, self.root, self.directory, self.seconds = docker, Path(root), Path(directory), seconds

    def observe(self, files, checks):
        directory = self.directory / ("check-" + uuid4().hex[:10])
        write_files(directory / "workspace", files)
        inputs = directory / "input"
        inputs.mkdir()
        (inputs / "checks.json").write_text(json.dumps(checks), encoding="utf-8")
        evaluator = directory / "evaluator"
        evaluator.mkdir()
        shutil.copyfile(self.root / "suites/coding/check_process.py", evaluator / "check_process.py")
        execution = self.docker.run(directory, entrypoint=("-I", "/evaluator/check_process.py", "/input/checks.json"),
                                    timeout=self.seconds, input_path=inputs, evaluator=evaluator)
        if not execution.succeeded:
            raise RuntimeError("EVALUATION_PROCESS_FAILED: " + str(directory / "process.log"))
        observed = read_json(directory / "results/observations.json")["observations"]
        if [item.get("id") for item in observed] != [item["id"] for item in checks]:
            raise ValueError("Missing, reordered or substituted evaluation cases")
        return observed

    def score(self, files, checks, expected):
        try:
            observed = self.observe(files, checks)
            failures = [case["id"] for case, wanted in zip(observed, expected, strict=True)
                        if case != wanted]
            return {"status": "PASS" if not failures else "FAIL", "cases": len(checks),
                    "failed": failures, "observations": observed}
        except (OSError, ValueError, RuntimeError) as error:
            return {"status": "EVALUATION_ERROR", "cases": len(checks), "reason": str(error)[:1000]}

    def qualify(self, recipe, reference):
        checks = checks_for(recipe)
        first = self.observe(reference, checks)
        second = self.observe(reference, checks)
        if first != second:
            raise ValueError("REFERENCE_CHECKS_UNSTABLE")
        relevant = [row for row in first if row["id"].startswith(recipe.task_id + ":")]
        if not any("value" in row["observation"] for row in relevant):
            raise ValueError("NO_SUCCESSFUL_REFERENCE_CASE")
        broken = dict(reference)
        broken[recipe.relative_file] = omit_function(reference[recipe.relative_file], recipe.symbol)
        negative = self.observe(broken, checks)
        changed = {row["id"] for row, expected in zip(negative, first, strict=True) if row != expected}
        if not changed or any(not item.startswith(recipe.task_id + ":") for item in changed):
            raise ValueError("INVALID_NEGATIVE_OR_PRESERVATION_CONTROL")
        public_indexes = [index for index, check in enumerate(checks) if int(check["id"].rsplit(":", 1)[1]) < 2]
        public_checks = [checks[index] for index in public_indexes]
        public_expected = [first[index] for index in public_indexes]
        # The reusable checker contains no test data. Only public cases are materialized.
        helper = (self.root / "suites/coding/check_process.py").read_text().split("\ndef main():", 1)[0]
        public_program = helper + "\nif __name__ == '__main__':\n"
        public_program += f"    actual = evaluate(Path.cwd(), {public_checks!r})\n"
        public_program += f"    if actual != {public_expected!r}:\n        raise AssertionError(actual)\n"
        public_program += f"    print('{len(public_checks)} public checks passed')\n"
        broken["public_tests.py"] = public_program
        broken["TASK.md"] = recipe.description + "\n\nRun public checks: python -B public_tests.py\n"
        return {"files": broken, "checks": checks, "expected": first,
                "public_checks": public_checks, "public_expected": public_expected,
                "qualification": {"reference_repeats": 2, "negative_detected": True,
                                  "preservation_unchanged": True, "case_count": len(checks)}}
