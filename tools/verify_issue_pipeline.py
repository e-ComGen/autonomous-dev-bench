"""Live GitHub/Docker qualification and replay gate. No paid model requests."""
from pathlib import Path
from dataclasses import replace
import json
import os
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages/benchmark_core")]
from suites.coding.settings import Settings
from suites.coding.docker_runtime import DockerRuntime
from suites.coding.issue_preparation import prepare, save_lock, restore_lock
from corpus.qualification.policy import IssuePolicy
from cli.oneclick.report import Report
from corpus.discovery.github import GitHubReader
from corpus.discovery.automatic import AutomaticIntake


def main():
    evidence = ROOT / "artifacts"
    evidence.mkdir(exist_ok=True)
    settings = Settings(check_seconds=90)
    policy = IssuePolicy(repositories=("pytest-dev/pluggy", "pallets/click", "encode/httpx"),
                         max_candidates=15, pulls_per_repository=50, prepare_seconds=900, build_seconds=180)
    report = Report(ROOT, "qualify")
    with tempfile.TemporaryDirectory(prefix="issue-live-") as temporary:
        runtime = DockerRuntime(ROOT, Path(temporary), settings)
        try:
            image = runtime.prepare_image()
            # Exercise unconstrained public repository discovery separately from the stable CI pool.
            automatic = replace(policy, repositories=(), repository_pool=30)
            reader = GitHubReader(os.environ["GITHUB_TOKEN"], report.cas, automatic)
            discovered = list(AutomaticIntake(reader, automatic, 71).repositories())
            if not discovered:
                raise ValueError("Automatic query returned no eligible Python packages")
            prepared = prepare(ROOT, runtime, report, settings, policy, 17)
            path = save_lock(report, 17, settings, policy, prepared)
            restored_seed, restored = restore_lock(ROOT / path, ROOT, runtime, report, settings, policy)
            if restored_seed != 17 or [task for task, _ in prepared] != [task for task, _ in restored]:
                raise ValueError("Exact replay changed tasks")
            task, data = prepared[0]
            candidate = data["captured"]["candidate"]
            result = {"status": "TASKS_QUALIFIED", "live_model_called": False,
                      "repository": task.project_id, "issue": candidate["issues"][0]["number"],
                      "pull": candidate["pull_number"], "base": candidate["pre_fix_commit"],
                      "fix": candidate["reference_commit"], "qualification": data["qualification"],
                      "qualification_repository_pool": list(policy.repositories),
                      "automatic_repository_results": [item[0]["nameWithOwner"] for item in discovered],
                      "replay_checked": True, "image": image}
            (evidence / "issue-qualification.json").write_text(json.dumps(result, indent=2))
            print(json.dumps({key: value for key, value in result.items() if key != "qualification"}, indent=2))
            print("FAIL_TO_PASS:", len(data["qualification"]["fail_to_pass"]),
                  "PASS_TO_PASS:", len(data["qualification"]["pass_to_pass"]))
        finally:
            for number, path in enumerate(list(runtime.scratch.rglob("process.log"))[:80]):
                text = path.read_text(encoding="utf-8", errors="replace")[-12000:]
                (evidence / f'qualification-{number}.log').write_text(text, encoding="utf-8")
            discovery = report.directory / "discovery.json"
            if discovery.is_file():
                details = json.loads(discovery.read_text())
                print(report.cas.get_text(details["details_ref"]))
            runtime.close()


if __name__ == "__main__":
    main()
