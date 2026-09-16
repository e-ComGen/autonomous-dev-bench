"""Safe, explicit CLI for the FAST zoning benchmark campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from benchmark_core.fast_zoning.manifest import InvalidManifest, validate_manifest
from benchmark_core.fast_zoning.runner import execute_pair, plan_campaign
from benchmark_core.fast_zoning.results import campaign_summary
from benchmark_core.fast_zoning.qualification_import import attach_packets, import_qualification, validate_import


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cli.fast_zoning")
    commands = parser.add_subparsers(dest="command", required=True)
    campaign = commands.add_parser("campaign")
    actions = campaign.add_subparsers(dest="action", required=True)
    validate = actions.add_parser("validate")
    validate.add_argument("manifest")
    validate.add_argument("--output", type=Path)
    plan = actions.add_parser("plan")
    plan.add_argument("manifest")
    plan.add_argument("--campaign-dir", type=Path, required=True)
    plan.add_argument("--pair-run-id", required=True)
    plan.add_argument("--dry-run", action="store_true", default=True)
    execute = actions.add_parser("execute")
    execute.add_argument("pair_dir", type=Path)
    execute.add_argument("--authorize-model-execution", action="store_true")
    execute.add_argument("--dry-run", action="store_true")
    summarize = actions.add_parser("summarize")
    summarize.add_argument("campaign_dir", type=Path)
    source_import = actions.add_parser("import-qualification")
    source_import.add_argument("source_repo", type=Path)
    source_import.add_argument("benchmark_repo", type=Path)
    source_import.add_argument("task_id")
    source_import.add_argument("--bundle-dir", type=Path, required=True)
    source_import.add_argument("--run-order-seed", required=True)
    source_import.add_argument("--output", type=Path)
    validate_import_parser = actions.add_parser("validate-import")
    validate_import_parser.add_argument("bundle_dir", type=Path)
    validate_import_parser.add_argument("--output", type=Path)
    bind = actions.add_parser("bind-packets")
    bind.add_argument("bundle_dir", type=Path)
    bind.add_argument("contexts", type=Path)
    bind.add_argument("--bundle-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "import-qualification":
            result = import_qualification(args.source_repo, args.benchmark_repo, args.task_id,
                                          args.bundle_dir, run_order_seed=args.run_order_seed)
        elif args.action == "validate-import":
            result = validate_import(args.bundle_dir)
        elif args.action == "bind-packets":
            result = attach_packets(args.bundle_dir, json.loads(args.contexts.read_text(encoding="utf-8")),
                                    args.bundle_output)
        elif args.action == "validate":
            manifest = validate_manifest(args.manifest)
            result = {"task_id": manifest["task_id"], "TASK_STATUS": "VALIDATED", "MODEL_EXECUTED": False}
        elif args.action == "plan":
            result = plan_campaign(args.manifest, args.campaign_dir, args.pair_run_id)
        elif args.action == "execute":
            if args.dry_run:
                result = {"TASK_STATUS": "PLANNED", "MODEL_EXECUTED": False, "pair_dir": str(args.pair_dir)}
            elif not args.authorize_model_execution:
                parser.error("execute requires --authorize-model-execution; use --dry-run for no model calls")
            else:
                result = execute_pair(args.pair_dir, authorized=True)
        else:
            pairs = [json.loads(path.read_text(encoding="utf-8"))
                     for path in sorted(args.campaign_dir.glob("tasks/*/*/paired-summary.json"))]
            states = list(args.campaign_dir.glob("tasks/*/*/state.json"))
            states.extend(args.campaign_dir.glob("invalid/*/state.json"))
            for path in sorted(states):
                if not (path.parent / "paired-summary.json").exists():
                    record = json.loads(path.read_text(encoding="utf-8"))
                    record.setdefault("pair_run_id", path.parent.name)
                    pairs.append(record)
            result = campaign_summary(pairs)
            (args.campaign_dir / "campaign-summary.json").write_text(
                json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    except InvalidManifest as exc:
        result = {"TASK_STATUS": "INVALID_MANIFEST", "MODEL_EXECUTED": False, "error": str(exc)}
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, default=str))
        return 2
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
