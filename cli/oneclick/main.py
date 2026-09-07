"""Operator composition root. Real issue A/B is default; self-tests remain explicit."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import sys
from .catalog import read_catalog
from .checks import doctor, run_checks
from .config import load_config
from .plan import make_plan
from .report import Report, atomic_write


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Automatic GitHub issue A/B and independent verification")
    result.add_argument("command", nargs="?", default="ab",
        choices=("ab", "ab-preflight", "qualify", "test", "doctor", "catalog", "plan", "projects", "discover", "_project"))
    result.add_argument("--config", default="BENCHMARK.toml")
    result.add_argument("--ab-config", default="AB.toml")
    result.add_argument("--seed", type=int)
    result.add_argument("--replay", help="Saved selection.json; reuses exact task/CAS/image bindings")
    result.add_argument("--allow-live-model", action="store_true")
    result.add_argument("--offline", action="store_true")
    result.add_argument("--allow-network", action="store_true")
    result.add_argument("--allow-local-build", action="store_true")
    result.add_argument("--source-dir", default=".bench/seeds")
    result.add_argument("--project")
    result.add_argument("--worker-output")
    return result


def execute(root: Path, arguments, config, catalog, report) -> dict:
    if arguments.command in {"ab", "ab-preflight", "qualify"}:
        from suites.coding.service import run_ab
        return run_ab(root, arguments, report)
    if arguments.command == "test":
        return run_checks(root, config, report)
    if arguments.command == "doctor":
        checks = doctor(root)
        return {"status": "CHECKED" if checks["git_available"] else "BLOCKED", **checks}
    if arguments.command == "catalog":
        return {"status": "CATALOG_READ", "projects": [
            {key: value for key, value in asdict(item).items() if key != "manifest_path"} for item in catalog]}
    if arguments.command == "plan":
        return make_plan(config, catalog)
    if arguments.command == "projects":
        from .preparation import prepare
        return prepare(root, config, catalog, report, config_path=Path(arguments.config).resolve(),
                       source_dir=Path(arguments.source_dir).resolve(), network=arguments.allow_network,
                       build=arguments.allow_local_build)
    if arguments.command == "discover":
        if not arguments.allow_network:
            raise ValueError("Discovery requires --allow-network")
        from corpus.discovery.service import collect
        return collect(config, report.cas)
    raise ValueError("Unknown command")


def worker(root: Path, arguments, config, catalog) -> int:
    from .project_worker import prepare_project
    output = Path(arguments.worker_output or "").resolve()
    if not output.is_relative_to((root / ".bench/runs").resolve()) or output.suffix != ".json":
        raise ValueError("Worker output must be in .bench/runs")
    selected = [entry for entry in catalog if entry.project_id == arguments.project]
    if len(selected) != 1:
        raise ValueError("Unknown project")
    try:
        result = prepare_project(root, selected[0], config, source_dir=Path(arguments.source_dir).resolve(),
                                 network=arguments.allow_network, build=arguments.allow_local_build)
    except (OSError, ValueError, RuntimeError) as error:
        result = {"status": "BLOCKED", "reason": str(error)[:1000]}
    atomic_write(output, json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] in {"SOURCE_VERIFIED", "BASELINE_CHECKED"} else 2


def main(root: Path) -> int:
    arguments = parser().parse_args()
    report = None
    try:
        if arguments.command != "_project":
            report = Report(root, arguments.command)
        if arguments.offline and arguments.allow_network:
            raise ValueError("--offline and --allow-network are mutually exclusive")
        config = load_config(Path(arguments.config).resolve())
        catalog = read_catalog(root)
        if arguments.command == "_project":
            return worker(root, arguments, config, catalog)
        result = execute(root, arguments, config, catalog, report)
        report.save(result)
        if result["status"] == "CANCELLED":
            return 130
        return 2 if result["status"] in {"FAILED", "BLOCKED", "INCOMPLETE", "PARTIAL", "AB_INCOMPLETE"} else 0
    except KeyboardInterrupt:
        if report:
            report.save({"status": "CANCELLED"})
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        if report:
            report.save({"status": "BLOCKED", "reason": str(error)[:1000]})
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
