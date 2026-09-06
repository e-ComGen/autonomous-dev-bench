from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

from benchmark_core.cas import FileSystemCAS
from benchmark_core.checkout import source_tree_digest
from benchmark_core.evidence import EvidenceBundleVerifier
from benchmark_core.identity import Sha256Digest, canonical_json
from benchmark_core.manifest import load_project, load_scenario, load_suite, load_task
from benchmark_core.result import HardGate


def _json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reject_answers(value: Any, path: str = "$") -> None:
    forbidden = {"expectation", "expectations", "expected_answer", "ground_truth", "labels", "oracle_labels"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in forbidden:
                raise ValueError(f"scenario leaks suite truth at {path}.{key}")
            _reject_answers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_answers(item, f"{path}[{index}]")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autonomous-dev-bench")
    sub = parser.add_subparsers(dest="command", required=True)
    digest = sub.add_parser("digest-json", help="print canonical JSON SHA-256")
    digest.add_argument("path")
    tree = sub.add_parser("digest-tree", help="print deterministic source-tree SHA-256")
    tree.add_argument("path")
    manifest = sub.add_parser("validate-manifest", help="load a manifest into its immutable schema")
    manifest.add_argument("kind", choices=("project", "task", "scenario", "suite")); manifest.add_argument("path")
    scenario = sub.add_parser("validate-scenario", help="reject expected answers in a scenario manifest")
    scenario.add_argument("path")
    cas = sub.add_parser("verify-cas", help="verify one CAS object")
    cas.add_argument("cas_root"); cas.add_argument("ref")
    evidence = sub.add_parser("verify-evidence", help="verify a canonical evidence bundle")
    evidence.add_argument("bundle"); evidence.add_argument("cas_root"); evidence.add_argument("expected_root")
    sub.add_parser("list-suites", help="list packaged capability-local suite manifests")
    gates = sub.add_parser("check-hard-gates", help="fail if a critical gate counter is nonzero")
    gates.add_argument("path")
    zoning = sub.add_parser("zoning-preview", help="preview advisory Auto-Zoning maps on pinned real projects")
    zoning.add_argument("--project", action="append", choices=("httpx", "requests", "pluggy", "httpx.pinned_001", "requests.pinned_001", "pluggy.pinned_001"))
    zoning.add_argument("--production-source", default=os.environ.get("AUTODEV_AUTOZONING_SOURCE"))
    zoning.add_argument("--autozoning-python", default=sys.executable)
    zoning.add_argument("--scope", action="append", default=[])
    zoning.add_argument("--runs", type=int, default=3)
    zoning.add_argument("--timeout", type=float, default=180.0)
    zoning.add_argument("--cache-root", default=".cache/zoning-preview")
    zoning.add_argument("--output-dir", default="reports/zoning-preview")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "digest-json":
            print(Sha256Digest.of(_json(args.path)))
        elif args.command == "digest-tree":
            print(source_tree_digest(args.path))
        elif args.command == "validate-manifest":
            loaders = {"project": load_project, "task": load_task, "scenario": load_scenario, "suite": load_suite}
            model = loaders[args.kind](args.path)
            print(model.content_digest)
        elif args.command == "validate-scenario":
            value = _json(args.path); _reject_answers(value)
            load_scenario(args.path)
            print(canonical_json(value))
        elif args.command == "verify-cas":
            FileSystemCAS(args.cas_root).verify(args.ref); print("CAS: PASS")
        elif args.command == "verify-evidence":
            manifest = EvidenceBundleVerifier(FileSystemCAS(args.cas_root)).verify(args.bundle, expected_root=args.expected_root)
            print(manifest["evidence_root_digest"])
        elif args.command == "list-suites":
            suites_root = Path(__file__).resolve().parents[1] / "suites"
            manifests = []
            for path in sorted(suites_root.glob("*/suite.v*.json")):
                value = load_suite(path)
                manifests.append({
                    "suite_id": value.suite_id, "suite_version": value.suite_version,
                    "input_checkpoint": value.input_checkpoint, "content_digest": str(value.content_digest),
                })
            print(canonical_json(manifests))
        elif args.command == "zoning-preview":
            from cli.zoning_preview import run_project_preview
            if not args.production_source:
                raise ValueError("--production-source or AUTODEV_AUTOZONING_SOURCE is required")
            projects = args.project or ["httpx", "requests", "pluggy"]
            if args.scope and len(projects) != 1:
                raise ValueError("--scope may only be used with one --project")
            reports = [run_project_preview(
                project, production_source=Path(args.production_source), python_executable=Path(args.autozoning_python),
                cache_root=Path(args.cache_root), output_dir=Path(args.output_dir), runs=args.runs,
                scope_paths=args.scope, timeout=args.timeout,
            ) for project in projects]
            summary = [{"project_id": item["project"]["project_id"], "status": item["status"],
                        "stability": item["stability"]["status"]} for item in reports]
            print(canonical_json(summary))
            if any(item["status"] == "INFRA_FAILURE" for item in reports): return 2
            if any(item["status"] != "PASS" for item in reports): return 1
        elif args.command == "check-hard-gates":
            counters = _json(args.path)
            if not isinstance(counters, dict): raise ValueError("hard-gate input must be an object")
            expected = {gate.value for gate in HardGate}
            unknown = set(counters) - expected
            missing = expected - set(counters)
            if unknown: raise ValueError("unknown hard gates: " + ", ".join(sorted(unknown)))
            if missing: raise ValueError("missing hard gates: " + ", ".join(sorted(missing)))
            if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counters.values()):
                raise ValueError("hard-gate counters must be non-negative integers")
            failed = [name for name, count in counters.items() if count > 0]
            if failed:
                print("hard gates: FAIL: " + ", ".join(sorted(failed)))
                return 1
            print("hard gates: PASS")
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
