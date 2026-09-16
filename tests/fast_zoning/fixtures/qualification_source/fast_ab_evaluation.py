"""Run only predeclared deterministic evaluators on a fresh candidate checkout."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from omp_zones.fast_ab import CLEAN_HEAD, evaluate, git, write_json
from omp_zones.fast_ab_results import plan_digest, validate_plan


def run_evaluators(plan: dict, workspace: Path, output: Path, *, narrow_result: dict | None = None) -> dict:
    validate_plan(plan)
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for index, evaluator in enumerate(plan["evaluators"]):
        directory = output / str(index)
        directory.mkdir()
        runner = evaluator["runner"]
        try:
            if runner == "frozen_oracle":
                if (narrow_result is not None
                        and narrow_result.get("oracle", {}).get("sha256") == evaluator["oracle_sha256"]
                        and Path(narrow_result["oracle"]["path"]).resolve() == Path(evaluator["oracle_path"]).resolve()):
                    observed = narrow_result
                else:
                    observed = evaluate(workspace, Path(evaluator["oracle_path"]), directory / "oracle.log",
                                        expected_hash=evaluator["oracle_sha256"])
                lines = Path(observed["log"]).read_text(encoding="utf-8", errors="replace").strip().splitlines()
                status = "PASS" if observed["success"] else "FAIL" if lines and re.match(r"^AssertionError(?::|$)", lines[-1]) else "ERROR"
                result = {"status": status, "detail": observed}
            elif runner == "pytest":
                if git(workspace, "status", "--porcelain", "--untracked-files=all", "--", "tests"):
                    raise ValueError("Candidate changed the frozen existing suite")
                xml = directory / "suite.xml"
                command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "--junitxml", str(xml.resolve()), *evaluator["args"]]
                env = dict(os.environ, PYTHONPATH=str(workspace / "src"),
                           PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
                process = subprocess.run(command, cwd=workspace, env=env, capture_output=True, timeout=240)
                (directory / "suite.log").write_bytes(process.stdout + process.stderr)
                counts = {key: sum(int(s.attrib.get(key, 0)) for s in ET.parse(xml).iter("testsuite"))
                          for key in ("tests", "failures", "errors", "skipped")}
                status = ("ERROR" if counts["errors"] or not counts["tests"] or process.returncode not in (0, 1)
                          else "FAIL" if counts["failures"] else "ERROR" if counts["skipped"] else "PASS")
                if process.returncode != 0 and status == "PASS":
                    status = "ERROR"
                result = {"status": status, **counts, "exit_code": process.returncode, "command": command}
            elif runner == "differential":
                dest = directory / "observed.json"
                command = [sys.executable, "-I", "-B", evaluator["probe_path"], str(workspace.resolve()),
                           evaluator["cases_path"], str(dest.resolve())]
                process = subprocess.run(command, capture_output=True, timeout=120)
                (directory / "probe.log").write_bytes(process.stdout + process.stderr)
                if process.returncode:
                    raise ValueError(f"Differential probe failed with exit {process.returncode}")
                expected_rows = json.loads(gzip.decompress(Path(evaluator["reference_path"]).read_bytes()))["results"]
                rows = json.loads(dest.read_text(encoding="utf-8"))["results"]
                expected = {row["id"]: row["outcome"] for row in expected_rows}
                actual = {row["id"]: row["outcome"] for row in rows}
                if not expected or actual.keys() != expected.keys() or len(actual) != len(rows):
                    raise ValueError("Differential case coverage mismatch")
                different = [key for key in expected if expected[key] != actual[key]]
                result = {"status": "FAIL" if different else "PASS", "cases_total": len(expected),
                          "cases_differ": len(different), "differing_case_ids": different, "command": command}
            else:
                result = {"status": "NOT_RUN", "reason": "External deterministic evidence has not been supplied"}
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError) as error:
            result = {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}
        results[evaluator["id"]] = result
        write_json(directory / "result.json", result)
    try:
        identical = (git(workspace, "diff", CLEAN_HEAD, "--", "src") == b""
                     and git(workspace, "ls-files", "--others", "--exclude-standard", "--", "src") == b"")
    except RuntimeError:
        identical = None
    return {"plan_digest": plan_digest(plan), "patch_valid": True, "evaluators": results,
            "production_matches_clean": identical}
