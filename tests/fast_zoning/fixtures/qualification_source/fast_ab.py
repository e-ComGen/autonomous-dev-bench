"""Reproducible context-policy A/B preparation; model execution is injected."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Protocol

from omp_zones import AutoZoningAnalysis, plan_zone_context, select_zone
from repository_intelligence.context import ContextBudget, ContextPlanner, ContextRequest
from repository_intelligence.lexical import LexicalSearchAdapter
from repository_intelligence.source import SourceMaterializer
from repository_intelligence.treesitter import TreeSitterFallback
from repository_intelligence.workspace import Workspace
from omp_zones.fast_ab_results import load_plan

S0_HEAD = "8fd4283085780b72a81c5ebd3ace2b30713e2e74"
S0_TREE = "9d632c9730e0e8c71cb52473fa0b0629399445ab"
CLEAN_HEAD = "a1b50bc12e066e5707ff797f821829bfcdab03b5"
CLEAN_TREE = "46b825df9a978ed7123b036fad5d712b362f0fbb"
ORACLE_HASH = "c5fa017ab08cc77210a2e0147c272dd8f2ea3374201ff303e7c559fd68a06e78"
DEFAULT_ORACLE = Path("C:/Users/Venya/ADCP/bench-results/fast-pilot-20260915/test_external_spoiler.py")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            timeout=120, env=env)
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def verify_copy(root: Path, head: str = S0_HEAD, tree: str = S0_TREE) -> dict:
    observed = {"head": git(root, "rev-parse", "HEAD").decode().strip(),
                "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
                "status": git(root, "status", "--porcelain", "--untracked-files=all").decode()}
    if observed != {"head": head, "tree": tree, "status": ""}:
        raise ValueError(f"Copy is not the frozen clean snapshot: {observed}")
    return observed | {"ready": True, "path": str(root.resolve())}


def clone_snapshot(source: Path, destination: Path, *, head: str = S0_HEAD,
                   tree: str = S0_TREE) -> dict:
    """Independent object database and worktree; refuses existing destinations."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    git(source, "clone", "--no-local", "--no-checkout", str(source.resolve()), str(destination.resolve()))
    git(destination, "-c", "core.autocrlf=false", "checkout", "--detach", head)
    git(destination, "config", "core.autocrlf", "false")
    return verify_copy(destination, head, tree)


def verify_oracle(oracle: Path, expected_hash: str = ORACLE_HASH) -> dict:
    actual = sha256(oracle.read_bytes())
    if actual != expected_hash:
        raise ValueError(f"ORACLE_IDENTITY_MISMATCH: {actual}")
    return {"path": str(oracle.resolve()), "sha256": actual}


def evaluate(workspace: Path, oracle: Path, log: Path, *, expected_hash: str = ORACLE_HASH,
             timeout: float = 120) -> dict:
    """Invoke frozen external oracle in its own interpreter, without candidate pytest hooks."""
    identity = verify_oracle(oracle, expected_hash)
    runner = Path(__file__).with_name("oracle_runner.py")
    command = [sys.executable, "-I", "-B", str(runner), identity["path"], expected_hash,
               str(workspace.resolve()), "test_top_level_block_spoiler"]
    started = perf_counter()
    result = subprocess.run(command, cwd=workspace, capture_output=True, timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(result.stdout + b"\n--- stderr ---\n" + result.stderr)
    verify_oracle(oracle, expected_hash)
    return {"success": result.returncode == 0, "exit_code": result.returncode,
            "wall_time": perf_counter() - started, "oracle": identity,
            "command": command, "log": str(log.resolve())}


def capture_patch(workspace: Path, artifact: Path, *, base: str = S0_HEAD) -> dict:
    """Capture all S0-relative bytes, including untracked/ignored and binary files.

    A temporary index leaves the candidate's staging area untouched. The manifest
    is the explicit changed-path inspection surface before evaluation.
    """
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fast-ab-index-") as directory:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(directory) / "index")
        git(workspace, "read-tree", base, env=env)
        git(workspace, "add", "--all", "--force", "--", ".", env=env)
        patch = git(workspace, "diff", "--cached", "--binary", "--full-index", "--no-renames", base, env=env)
        paths = [p.decode("utf-8") for p in git(workspace, "diff", "--cached", "--name-only",
                                              "--no-renames", "-z", base, env=env).split(b"\0") if p]
        status_fields = git(workspace, "diff", "--cached", "--name-status", "--find-renames",
                            "-z", base, env=env).split(b"\0")
        changes = []
        cursor = 0
        while cursor < len(status_fields) and status_fields[cursor]:
            status = status_fields[cursor].decode("ascii")
            count = 2 if status[0] in ("R", "C") else 1
            names = [field.decode("utf-8") for field in status_fields[cursor + 1:cursor + 1 + count]]
            changes.append({"status": status, "path": names[-1],
                            "old_path": names[0] if count == 2 else None})
            cursor += 1 + count
    artifact.write_bytes(patch)
    result = {"base": base, "patch": str(artifact.resolve()), "sha256": sha256(patch),
              "patch_size": len(patch), "changed_files": paths,
              "includes_untracked": True, "includes_ignored": True, "path_changes": changes}
    write_json(artifact.with_suffix(".manifest.json"), result)
    return result


def evaluate_candidate(source: Path, candidate: Path, destination: Path, oracle: Path,
                       artifact: Path) -> dict:
    patch = capture_patch(candidate, artifact)
    clone_snapshot(source, destination)
    if patch["patch_size"]:
        git(destination, "apply", "--binary", "--check", str(artifact.resolve()))
        git(destination, "apply", "--binary", str(artifact.resolve()))
    return {"patch": patch, "oracle_result": evaluate(destination, oracle, artifact.with_suffix(".oracle.log"))}


@dataclass
class ArmMetrics:
    arm: str
    success: bool | None = None
    oracle_result: dict | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    model_turns: int | None = None
    tool_calls: int | None = None
    files_read: list[str] | None = None
    packet_bytes: int | None = None
    source_bytes: int | None = None
    zoning_time: float | None = None
    planning_time: float | None = None
    preprocessing_wall_time: float | None = None
    model_wall_time: float | None = None
    total_wall_time: float | None = None
    retries: int | None = None
    patch_size: int | None = None
    changed_files: list[str] | None = None
    provider_cost: float | None = None
    provider_quota: dict | None = None
    model_executed: bool = False


class CoderAdapter(Protocol):
    def __call__(self, workspace: Path, task: str, context_packet: bytes,
                 execution_config: dict) -> dict: ...


def run_coder(workspace: Path, task: str, context_packet: bytes,
              execution_config: dict, *, adapter: CoderAdapter) -> dict:
    """Only execution seam for both arms. Supply the OMP worker's tested adapter."""
    return adapter(workspace, task, context_packet, execution_config)


def paired_summary(a: ArmMetrics, b: ArmMetrics) -> dict:
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens",
              "packet_bytes", "source_bytes", "zoning_time", "planning_time", "model_wall_time",
              "total_wall_time", "provider_cost")
    deltas = {}
    for field in fields:
        av, bv = getattr(a, field), getattr(b, field)
        deltas[field] = None if av is None or bv is None else bv - av
    return {"A": asdict(a), "B": asdict(b), "B_minus_A": deltas,
            "AB_PAIR_COMPLETED": a.model_executed and b.model_executed
            and a.oracle_result is not None and b.oracle_result is not None,
            "ECONOMY_MEASURED": a.model_executed and b.model_executed
            and a.input_tokens is not None and b.input_tokens is not None}


def packet_record(encoded: bytes, path: Path, planning_time: float,
                  zoning_time: float, preprocessing: float) -> dict:
    path.write_bytes(encoded)
    bundle = json.loads(encoded)
    sources = [item for item in bundle["items"] if item.get("source")]
    return {"path": str(path.resolve()), "sha256": sha256(encoded), "packet_bytes": len(encoded),
            "source_item_count": len(sources),
            "source_bytes": sum(len(item["source"].encode("utf-8")) for item in sources),
            "included_paths": sorted({item["path"] for item in bundle["items"]}),
            "included_symbols": [item.get("label") for item in bundle["items"] if item.get("label")],
            "body_subjects": [item["subject"] for item in sources if item["level"] == "body"],
            "planning_time": planning_time, "zoning_time": zoning_time,
            "preprocessing_wall_time": preprocessing, "warnings": bundle["warnings"],
            "incomplete": bundle["incomplete"]}


def prepare(source: Path, output: Path, task: str, target_paths: tuple[str, ...], *,
            oracle: Path = DEFAULT_ORACLE, budget: ContextBudget | None = None) -> dict:
    """Prepare one frozen pair. Never calls run_coder and never reuses a run directory."""
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(output)
    verify_copy(source)
    if git(source, "rev-parse", CLEAN_HEAD + "^{tree}").decode().strip() != CLEAN_TREE:
        raise ValueError("Clean benchmark tree mismatch")
    identity = verify_oracle(oracle)
    output.mkdir(parents=True)
    # Future acceptance requirements are persisted before any model invocation.
    evaluation_plan = load_plan(Path(__file__).with_name("evaluation") / "mistune-v2.json")
    write_json(output / "evaluation-plan.json", evaluation_plan)
    effective_budget = budget or ContextBudget(max_bytes=16000, max_source_bytes=8000,
                                                max_facts=32, max_queries=16, max_files=12)
    task_bytes = task.encode("utf-8")
    (output / "task.txt").write_bytes(task_bytes)
    write_json(output / "request.json", {"task_sha256": sha256(task_bytes),
               "target_paths": target_paths, "budget": asdict(effective_budget),
               "execution_config": None, "execution_contract": "AWAITING_OMP_WORKER"})
    records, metrics, copies = {}, {}, {}
    for arm in ("A", "B"):
        root = output / f"run-{arm}"
        copies[arm] = clone_snapshot(source, root)
        start = perf_counter()
        workspace = Workspace(root, "mistune-fast-zoning-ab-v1")
        zoning_time = 0.0
        provenance = None
        if arm == "A":
            planner = ContextPlanner(TreeSitterFallback(workspace), SourceMaterializer(workspace),
                                     LexicalSearchAdapter(workspace))
            request = ContextRequest(task=task, diff_paths=target_paths, budget=effective_budget)
            planning_start = perf_counter()
            encoded = planner.plan(request).encode()
            planning_time = perf_counter() - planning_start
        else:
            zoning_start = perf_counter()
            analysis = AutoZoningAnalysis.run(root)
            if not analysis.source_consistent or not analysis.snapshot_ref or not analysis.analysis_digest:
                raise ValueError("Auto-Zoning source provenance incomplete")
            selection = select_zone(analysis, task, target_paths=target_paths)
            zoning_time = perf_counter() - zoning_start
            write_json(output / "autozoning.json", asdict(analysis))
            write_json(output / "zone.json", selection.to_dict())
            planning_start = perf_counter()
            encoded = plan_zone_context(workspace, selection, task, budget=effective_budget).bundle_bytes
            planning_time = perf_counter() - planning_start
            total_units = sum(analysis.attributed_units_for.values())
            zone_shares = [{"artifact_path": record["artifact_path"], **share}
                           for record in analysis.files for share in record.get("zone_shares", ())
                           if share.get("zone_id") == selection.zone_id]
            provenance = {"ZONE_ID": selection.zone_id, "ZONE_ARTIFACT_PATHS": selection.artifact_paths,
                          "ZONE_SHARE": zone_shares,
                          "TARGET_ZONE_SHARES": [share for share in zone_shares
                                                 if share["artifact_path"] in target_paths],
                          "GLOBAL_ATTRIBUTED_UNIT_RATIO": selection.attributed_units / total_units if total_units else None,
                          "ANALYSIS_STATUS": analysis.status, "SOURCE_CONSISTENT": analysis.source_consistent,
                          "ANALYSIS_DIGEST": analysis.analysis_digest, "SNAPSHOT_ID": analysis.snapshot_ref}
        records[arm] = packet_record(encoded, output / f"{arm}_CONTEXT_PACKET", planning_time,
                                     zoning_time, perf_counter() - start)
        records[arm]["provenance"] = provenance
        items = json.loads(encoded)["items"]
        records[arm]["target_body_materialized"] = any(
            item.get("level") == "body" and item.get("source") and item.get("provider") == "tree-sitter"
            and item.get("path") in target_paths and item.get("label") == "depth" for item in items)
        write_json(output / f"{arm}_context.json", records[arm])
        metrics[arm] = ArmMetrics(arm, packet_bytes=len(encoded), source_bytes=records[arm]["source_bytes"],
                                 zoning_time=zoning_time, planning_time=planning_time,
                                 preprocessing_wall_time=records[arm]["preprocessing_wall_time"])
        write_json(output / f"{arm}_metrics.json", asdict(metrics[arm]))
        verify_copy(root)
    qualification = {}
    for name, head, tree in (("buggy", S0_HEAD, S0_TREE), ("clean", CLEAN_HEAD, CLEAN_TREE)):
        root = output / f"evaluator-{name}"
        clone_snapshot(source, root, head=head, tree=tree)
        qualification[name] = evaluate(root, oracle, output / f"oracle-{name}.log")
    evaluator_ready = not qualification["buggy"]["success"] and qualification["clean"]["success"]
    summary = paired_summary(metrics["A"], metrics["B"])
    summary.update({"BENCHMARK_HEAD": S0_HEAD, "BENCHMARK_TREE": S0_TREE,
                    "packets": records, "copies": copies, "oracle": identity,
                    "evaluator_qualification": qualification, "EVALUATOR_READY": evaluator_ready,
                    "METRICS_READY": True, "EXECUTION_SEAM_READY": True,
                    "EXECUTION_CONTRACT_READY": False,
                    "AB_INFRA_READY": evaluator_ready and all(record["target_body_materialized"] for record in records.values()),
                    "MODEL_EXECUTED_A": False, "MODEL_EXECUTED_B": False})
    write_json(output / "paired-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--target-path", action="append", required=True)
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    args = parser.parse_args()
    prepare(args.source, args.output, args.task_file.read_text(encoding="utf-8"),
            tuple(args.target_path), oracle=args.oracle)
    print(str(args.output.resolve() / "paired-summary.json"))


if __name__ == "__main__":
    main()
