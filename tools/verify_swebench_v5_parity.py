"""Run the Phase 1 official SWE-bench v5 empty/gold parity gate."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "benchmark_core")]

from benchmark_core.swebench_v5 import OfficialSwebenchV5, SwebenchPrediction, require_v5, write_predictions


DEFAULT_PLAN = ROOT / "migration" / "swebench_v5_verified_parity.json"


def load_plan(path: Path) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("scope") != "PHASE1_OFFICIAL_SWEBENCH_V5_PARITY_NOT_MODEL_AB":
        raise ValueError("unexpected parity plan scope")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or len(tasks) < 10 or len(set(tasks)) != len(tasks):
        raise ValueError("parity plan requires at least 10 unique tasks")
    return plan


def run(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=False)


def report_ids(report: dict[str, object], key: str) -> set[str]:
    values = report.get(key)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"official report missing valid {key}")
    return set(values)


def assert_no_infrastructure_failure(report: dict[str, object], label: str) -> None:
    failures = {
        "infra_failure_ids": report_ids(report, "infra_failure_ids"),
        "ambiguous_failure_ids": report_ids(report, "ambiguous_failure_ids"),
        "error_ids": report_ids(report, "error_ids"),
    }
    nonempty = {name: sorted(values) for name, values in failures.items() if values}
    if nonempty:
        raise ValueError(f"{label} contains infrastructure/evaluator failures: {nonempty}")


def local_image_id(image: str) -> str | None:
    """Return a local content ID when official evaluation retained the image."""

    inspected = subprocess.run(
        ("docker", "image", "inspect", "--format={{.Id}}", image),
        check=False,
        text=True,
        capture_output=True,
    )
    if inspected.returncode != 0:
        return None
    image_id = inspected.stdout.strip()
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ValueError(f"unexpected Docker image ID for {image}: {image_id!r}")
    return image_id


def environment_evidence(task_repo: Path, tasks: tuple[str, ...]) -> dict[str, object]:
    """Record task-repo-owned environment identities without depending on cleanup policy."""

    from swebench.task.repo import load_task_repo

    instances = load_task_repo(task_repo, list(tasks))
    if {instance["instance_id"] for instance in instances} != set(tasks):
        raise ValueError("official task repo did not load the exact parity cohort")

    evidence = {}
    for instance in instances:
        instance_id = instance["instance_id"]
        image = instance.get("image")
        if not isinstance(image, str) or not image:
            raise ValueError(f"{instance_id} has no image identity")
        dockerfile = task_repo / "tasks" / instance_id / "Dockerfile"
        evidence[instance_id] = {
            "image": image,
            "local_image_id": local_image_id(image),
            "dockerfile_sha256": hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
            "base_commit": instance.get("base_commit"),
        }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--task-repo", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "artifacts" / "swebench-v5-parity")
    parser.add_argument("--swebench", default="swebench")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    plan = load_plan(args.plan)
    tasks = tuple(plan["tasks"])
    expected_version = str(plan["official_swebench"]["version"])
    task_repo_pin = str(plan["task_repo"]["commit"])

    try:
        installed_version = package_version("swebench")
    except PackageNotFoundError as error:
        raise ValueError("official swebench package is not installed") from error
    actual_version = require_v5(installed_version)
    if ".".join(str(part) for part in actual_version) != expected_version:
        raise ValueError(f"expected swebench {expected_version}, observed {installed_version}")

    if not args.task_repo.is_dir():
        raise ValueError("task repo path does not exist")
    observed_task_repo_pin = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=args.task_repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip().lower()
    if observed_task_repo_pin != task_repo_pin:
        raise ValueError(f"task repo pin mismatch: expected {task_repo_pin}, observed {observed_task_repo_pin}")

    evaluator = OfficialSwebenchV5(
        executable=args.swebench,
        dataset=str(plan["dataset"]),
        workers=args.workers,
        timeout_seconds=args.timeout,
        task_repo=args.task_repo.resolve(),
    )
    args.work_dir.mkdir(parents=True, exist_ok=True)
    predictions = args.work_dir / "empty-predictions.jsonl"
    write_predictions(
        predictions,
        (SwebenchPrediction(task, "", "autonomous-dev-bench-empty-control") for task in tasks),
    )

    empty_run_id = "phase1-empty"
    gold_run_id = "phase1-gold"
    run(evaluator.prediction_command(empty_run_id, tasks, predictions.resolve()), args.work_dir)
    empty_report = evaluator.load_results(args.work_dir, empty_run_id)
    assert_no_infrastructure_failure(empty_report, "empty control")
    if report_ids(empty_report, "empty_patch_ids") != set(tasks):
        raise ValueError("empty control did not classify every cohort task as an empty patch")
    if report_ids(empty_report, "resolved_ids"):
        raise ValueError("empty control unexpectedly resolved a task")

    run(evaluator.gold_command(gold_run_id, tasks), args.work_dir)
    gold_report = evaluator.load_results(args.work_dir, gold_run_id)
    assert_no_infrastructure_failure(gold_report, "gold control")
    if report_ids(gold_report, "resolved_ids") != set(tasks):
        unresolved = sorted(set(tasks) - report_ids(gold_report, "resolved_ids"))
        raise ValueError(f"gold control failed parity for: {unresolved}")
    if report_ids(gold_report, "unresolved_ids") or report_ids(gold_report, "empty_patch_ids"):
        raise ValueError("gold control contains unresolved or empty-patch outcomes")

    images = environment_evidence(args.task_repo.resolve(), tasks)
    evidence = {
        "scope": plan["scope"],
        "status": "PASS",
        "model_called": False,
        "dataset": plan["dataset"],
        "tasks": list(tasks),
        "official_swebench_version": expected_version,
        "task_repo_commit": task_repo_pin,
        "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        "environments": images,
        "empty_run": empty_report,
        "gold_run": gold_report,
        "legacy_canary": plan["legacy_canary"],
    }
    evidence_path = args.work_dir / "PHASE1_SWEBENCH_V5_PARITY.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 1 parity: PASS ({len(tasks)} tasks); evidence={evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
