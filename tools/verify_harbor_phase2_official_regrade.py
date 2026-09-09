"""Re-grade one Harbor-produced probe patch with the pinned official SWE-bench v5 evaluator."""

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


INSTANCE_ID = "psf__requests-1142"
MODEL_NAME = "harbor-phase2-official-regrade-probe"
MARKER = "AUTOBENCH_TRANSPORT_PROBE.txt"
EXPECTED_TEXT = "harbor official regrade transport probe"
DEFAULT_PLAN = ROOT / "migration" / "swebench_v5_verified_parity.json"


def unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def report_ids(report: dict[str, object], key: str) -> set[str]:
    values = report.get(key)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"official SWE-bench report missing valid {key}")
    return set(values)


def run(command: tuple[str, ...], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--task-repo", type=Path, required=True)
    parser.add_argument("--official-image-id", required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "artifacts" / "harbor-phase2" / "official-regrade",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "harbor-phase2" / "PHASE2_OFFICIAL_SWEBENCH_REGRADE.json",
    )
    args = parser.parse_args()

    if not args.official_image_id.startswith("sha256:"):
        raise ValueError("captured official image id must be content-addressed")

    plan = load_json(args.plan)
    expected_version = str(plan["official_swebench"]["version"])
    expected_task_repo_commit = str(plan["task_repo"]["commit"])
    if INSTANCE_ID not in plan.get("tasks", []):
        raise ValueError(f"official re-grade instance is not in the accepted Phase 1 parity cohort: {INSTANCE_ID}")

    try:
        observed_version = package_version("swebench")
    except PackageNotFoundError as error:
        raise ValueError("official swebench package is not installed") from error
    parsed_version = require_v5(observed_version)
    if ".".join(str(part) for part in parsed_version) != expected_version:
        raise ValueError(f"expected swebench {expected_version}, observed {observed_version}")

    task_repo = args.task_repo.resolve()
    observed_task_repo_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=task_repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip().lower()
    if observed_task_repo_commit != expected_task_repo_commit:
        raise ValueError(
            f"task repo pin mismatch: expected {expected_task_repo_commit}, observed {observed_task_repo_commit}"
        )

    from swebench.task.repo import load_task_repo

    instances = load_task_repo(task_repo, [INSTANCE_ID])
    if len(instances) != 1 or instances[0].get("instance_id") != INSTANCE_ID:
        raise ValueError("pinned task repo did not load the expected official task")
    instance = instances[0]
    image = instance.get("image")
    base_commit = instance.get("base_commit")
    if not isinstance(image, str) or not image or not isinstance(base_commit, str) or len(base_commit) != 40:
        raise ValueError("official task lacks image/base provenance")
    image_id = args.official_image_id

    result_path = unique_file(args.trials_dir, "result.json")
    patch_path = unique_file(args.trials_dir, "PATCH.diff")
    probe_path = unique_file(args.trials_dir, "OFFICIAL_REGRADE_PROBE.json")
    harbor_result = load_json(result_path)
    probe = load_json(probe_path)
    patch = patch_path.read_text(encoding="utf-8")

    if harbor_result.get("exception_info") is not None:
        raise ValueError(f"Harbor transport trial failed: {harbor_result['exception_info']}")
    context = harbor_result.get("agent_result")
    metadata = context.get("metadata") if isinstance(context, dict) else None
    benchmark_meta = metadata.get("autonomous_dev_bench") if isinstance(metadata, dict) else None
    if not isinstance(benchmark_meta, dict) or benchmark_meta.get("model_called") is not False:
        raise ValueError("Harbor official re-grade probe does not prove zero model calls")
    for key, expected in (
        ("n_input_tokens", 0),
        ("n_cache_tokens", 0),
        ("n_output_tokens", 0),
        ("cost_usd", 0.0),
    ):
        if context.get(key) != expected:
            raise ValueError(f"Harbor official re-grade probe {key} mismatch: {context.get(key)!r}")
    if probe.get("model_called") is not False or probe.get("repository_root") != "/testbed":
        raise ValueError("Harbor official re-grade probe identity is incomplete")

    if patch.count("diff --git ") != 1 or MARKER not in patch or f"+{EXPECTED_TEXT}" not in patch:
        raise ValueError("Harbor transport patch contains unexpected changes")
    forbidden_fragments = ("gold.patch", "test.patch", "FAIL_TO_PASS", "PASS_TO_PASS")
    if any(fragment in patch for fragment in forbidden_fragments):
        raise ValueError("Harbor transport patch contains benchmark answer/test material")
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if probe.get("patch_sha256") != patch_sha256:
        raise ValueError("Harbor probe patch digest does not match exported patch")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    predictions = args.work_dir / "harbor-transport-prediction.jsonl"
    write_predictions(predictions, [SwebenchPrediction(INSTANCE_ID, patch, MODEL_NAME)])
    evaluator = OfficialSwebenchV5(
        dataset=str(plan["dataset"]),
        workers=1,
        timeout_seconds=1800,
        task_repo=task_repo,
    )
    run_id = "phase2-harbor-official-regrade"
    run(evaluator.prediction_command(run_id, [INSTANCE_ID], predictions.resolve()), args.work_dir)
    report = evaluator.load_results(args.work_dir, run_id)

    if report_ids(report, "resolved_ids"):
        raise ValueError("harmless Harbor transport patch unexpectedly resolved the SWE-bench task")
    if report_ids(report, "unresolved_ids") != {INSTANCE_ID}:
        raise ValueError(f"official evaluator did not classify the transport patch as unresolved: {report}")
    if report_ids(report, "empty_patch_ids"):
        raise ValueError("official evaluator treated the non-empty Harbor patch as empty")
    failures = {
        "infra_failure_ids": report_ids(report, "infra_failure_ids"),
        "ambiguous_failure_ids": report_ids(report, "ambiguous_failure_ids"),
        "error_ids": report_ids(report, "error_ids"),
    }
    nonempty_failures = {key: sorted(value) for key, value in failures.items() if value}
    if nonempty_failures:
        raise ValueError(f"official re-grade contains infrastructure/evaluator failures: {nonempty_failures}")

    evidence = {
        "scope": "PHASE2_HARBOR_TO_OFFICIAL_SWEBENCH_REGRADE",
        "status": "PASS",
        "paid_model_called": False,
        "instance_id": INSTANCE_ID,
        "dataset": plan["dataset"],
        "official_swebench_version": expected_version,
        "task_repo_commit": expected_task_repo_commit,
        "task_base_commit": base_commit,
        "official_image": image,
        "official_image_id": image_id,
        "harbor_environment_id": probe.get("environment_id"),
        "harbor_workspace_head": probe.get("baseline_commit"),
        "patch_sha256": patch_sha256,
        "patch_bytes": len(patch.encode("utf-8")),
        "official_outcome": "UNRESOLVED",
        "official_report": report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "Harbor -> official SWE-bench v5 re-grade: PASS "
        f"instance={INSTANCE_ID} outcome=UNRESOLVED patch_sha256={patch_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
