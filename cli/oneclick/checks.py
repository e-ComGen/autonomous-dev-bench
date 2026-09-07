"""Run the existing suite and bundled negative control using ProcessRunner."""
from pathlib import Path
import shutil
import sys
import tempfile

from benchmark_core.execution import CommandSpec, ProcessRunner
from .catalog import read_catalog
from .selftest import run_selftest
from .test_results import junit_counts, log_result, test_succeeded


def doctor(root: Path) -> dict:
    return {"python": sys.version.split()[0], "python_supported": sys.version_info >= (3, 11),
            "git_available": shutil.which("git") is not None,
            "catalog_projects": len(read_catalog(root)),
            "selftest_present": (root / "reference_projects/benchmark_selftest_project").is_dir(),
            "external_models_required": False}


def run_checks(root: Path, config, report) -> dict:
    prerequisites = doctor(root)
    if not prerequisites["git_available"] or not prerequisites["selftest_present"]:
        return {"status": "BLOCKED", "prerequisites": prerequisites,
                "reason": "GIT_OR_BUNDLED_PROJECT_MISSING"}
    junit = report.directory / "repository-tests.xml"
    # Keep pytest's owned scratch close to the checkout root. Nesting the
    # default pytest hierarchy below managed TMP exceeds Git for Windows'
    # separate GIT_DIR bound, even when core.longpaths is enabled.
    # Only this newly allocated directory can be cleared by --basetemp.
    with tempfile.TemporaryDirectory(prefix="p", dir=root / ".bench") as scratch:
        command = CommandSpec((sys.executable, "-B", "-m", "pytest", "-q", "--color=no",
                               "--tb=short", "-p", "no:cacheprovider", "--basetemp=" + scratch,
                               "--junitxml=" + str(junit), "tests"),
                              config.budgets.test_seconds, str(root))
        result = ProcessRunner().run(command)
    log = log_result(report, "repository-tests", result)
    if result.timed_out or not junit.is_file():
        return {"status": "FAILED", "suite": log, "reason": "TEST_TIMEOUT_OR_NO_JUNIT"}
    counts = junit_counts(junit)
    if not test_succeeded(result, counts):
        return {"status": "FAILED", "suite": {**log, **counts}}
    control = run_selftest(root, report, min(60, config.budgets.baseline_seconds))
    status = "CHECKED" if control["status"] == "SELFTEST_OK" else "FAILED"
    print(f"Tests: {counts['tests']}; failures: {counts['failures']}; errors: {counts['errors']}; skipped: {counts['skipped']}")
    print(f"Bundled source negative control: {control['status']}")
    return {"status": status, "prerequisites": prerequisites, "suite": {**log, **counts},
            "selftest": control, "coding_quality_measured": False,
            "skipped_tests_are_not_coverage": True}
