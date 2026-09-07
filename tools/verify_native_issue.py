"""Real GitHub issue acquisition/build/tests/replay with native processes, no Docker/model."""
from dataclasses import replace
from pathlib import Path
import json
import os
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.backends.native import NativeRuntime
from suites.coding.issue_preparation import prepare, save_lock, restore_lock
from corpus.qualification.policy import IssuePolicy
from corpus.qualification.files import text
from cli.oneclick.report import Report


def main():
    evidence = ROOT / "artifacts"
    evidence.mkdir(exist_ok=True)
    settings = replace(Settings(), execution_backend="native", check_seconds=180)
    # The CI pool is explicit; production retains automatic project discovery.
    policy = IssuePolicy(repositories=("pytest-dev/pluggy", "pallets/click", "encode/httpx"),
                         max_candidates=15, pulls_per_repository=50, prepare_seconds=900, build_seconds=300)
    report = Report(ROOT, "qualify")
    with tempfile.TemporaryDirectory(prefix="issue-") as temporary:
        runtime = NativeRuntime(ROOT, Path(temporary), settings)
        try:
            runtime.prepare_image()
            prepared = prepare(ROOT, runtime, report, settings, policy, 17)
            path = save_lock(report, 17, settings, policy, prepared)
            seed, restored = restore_lock(ROOT / path, ROOT, runtime, report, settings, policy)
            if seed != 17 or [task for task, _ in prepared] != [task for task, _ in restored]:
                raise ValueError("Native exact replay changed task identity")
            task, data = prepared[0]
            evaluator = data["evaluator"]
            empty = evaluator.score(data["captured"]["projection"], data["checks"], data["expected"])
            reference = {**data["captured"]["projection"],
                **{path: text(record) for path, record in data["captured"]["fix_code"].items()}}
            fixed = evaluator.score(reference, data["checks"], data["expected"])
            if empty["status"] != "FAIL" or fixed["status"] != "PASS":
                raise ValueError("Native patch negative/positive controls did not discriminate")
            candidate = data["captured"]["candidate"]
            result = {"platform": sys.platform, "backend": "native", "docker_invoked": False,
                "paid_model_called": False, "status": "TASKS_QUALIFIED", "repository": task.project_id,
                "issue": candidate["issues"][0]["number"], "pull": candidate["pull_number"],
                "base": candidate["pre_fix_commit"], "fix": candidate["reference_commit"],
                "fail_to_pass": len(data["qualification"]["fail_to_pass"]),
                "pass_to_pass": len(data["qualification"]["pass_to_pass"]), "replay_checked": True,
                "empty_patch": empty["status"], "reference_patch": fixed["status"],
                "qualification_repository_pool": list(policy.repositories), "environment": data["image"]}
            (evidence / "native-issue.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            for index, path in enumerate(list(runtime.scratch.rglob("process.log"))[:40]):
                value = path.read_text(encoding="utf-8", errors="replace")[-12000:]
                (evidence / f"issue-process-{index}.log").write_text(value, encoding="utf-8")
            discovery = report.directory / "discovery.json"
            if discovery.is_file():
                pointer = json.loads(discovery.read_text())
                print(report.cas.get_text(pointer["details_ref"]))
            runtime.close()


if __name__ == "__main__":
    main()
