"""Parse pytest's machine report without accepting prose as a verdict."""
from pathlib import Path
import xml.etree.ElementTree as ET

from benchmark_core.execution import ExecutionResult


def junit_counts(path: Path) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size > 8388608:
        raise ValueError("Missing or oversized JUnit report")
    root = ET.fromstring(path.read_bytes())
    counts = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
    suites = list(root.iter("testsuite"))
    if not suites:
        raise ValueError("JUnit has no test suites")
    for suite in suites:
        for name in counts:
            value = int(suite.attrib.get(name, "0"))
            if value < 0:
                raise ValueError("Invalid JUnit count")
            counts[name] += value
    if counts["tests"] == 0:
        raise ValueError("Zero collected tests is not success")
    return counts


def test_succeeded(result: ExecutionResult, counts: dict[str, int]) -> bool:
    return result.succeeded and counts["tests"] > counts["skipped"] and not (
        counts["failures"] or counts["errors"])


def log_result(report, name: str, result: ExecutionResult) -> dict:
    text = result.stdout + "\n" + result.stderr
    raw = text.encode("utf-8")
    limited = raw[:262144]
    path = report.directory / (name + ".log")
    path.write_bytes(limited)
    return {"returncode": result.returncode, "timed_out": result.timed_out,
            "wall_seconds": result.wall_time_seconds,
            "log_ref": report.cas.put_bytes(limited), "log_truncated": len(raw) > len(limited)}
