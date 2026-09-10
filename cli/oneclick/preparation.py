"""Bounded sequential preparation over the same project roster; no new scheduler."""
from pathlib import Path
import json
import sys

from benchmark_core.execution import CommandSpec, ProcessRunner
from .plan import make_plan
from .test_results import log_result


def prepare(root: Path, config, catalog, report, *, config_path: Path,
            source_dir: Path, network: bool, build: bool) -> dict:
    plan = make_plan(config, catalog)
    results = []
    for item in plan["projects"]:
        output = report.directory / (item["id"] + ".json")
        arguments = [sys.executable, "-B", str(root / "tools/bench.py"), "_project",
                     "--config", str(config_path), "--project", item["id"],
                     "--source-dir", str(source_dir), "--worker-output", str(output)]
        if network:
            arguments.append("--allow-network")
        if build:
            arguments.append("--allow-local-build")
        execution = ProcessRunner().run(CommandSpec(tuple(arguments), config.budgets.project_seconds, str(root)))
        log = log_result(report, item["id"], execution)
        if execution.succeeded and output.is_file() and output.stat().st_size < 131072:
            result = json.loads(output.read_text(encoding="utf-8"))
        else:
            result = {"project_id": item["id"], "status": "TIMEOUT" if execution.timed_out else "BLOCKED"}
            if output.is_file() and output.stat().st_size < 131072:
                result["reason"] = json.loads(output.read_text(encoding="utf-8")).get("reason")
            else:
                result["reason"] = "WORKER_NO_RECEIPT"
        result["process"] = log
        results.append(result)
        explanation = str(result.get("reason") or "").replace("\n", " ")[:300]
        print(f"{item['id']}: {result['status']}" + (f" — {explanation}" if explanation else ""), flush=True)
        if result.get("reason") == "WORKER_NO_RECEIPT":
            print("Worker diagnostics: " + (execution.stderr or execution.stdout)[-1500:], flush=True)
    successes = {"SOURCE_VERIFIED", "BASELINE_CHECKED"}
    ready = not plan["quota_deficits"] and bool(results) and all(item["status"] in successes for item in results)
    return {"status": "PREPARED" if ready else "INCOMPLETE", "projects": results,
            "quota_deficits": plan["quota_deficits"], "coding_quality_measured": False,
            "qualified_coding_tasks": 0, "source_network_allowed": network}
