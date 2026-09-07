"""Parent-side time bound over the existing Git cache worker and CAS."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
from uuid import uuid4
from benchmark_core.execution import CommandSpec, ProcessRunner


def acquire_bounded(root, candidate, policy, seconds, report):
    directory = report.directory / ("capture-" + uuid4().hex[:8])
    directory.mkdir()
    request, response = directory / "request.json", directory / "response.json"
    request.write_text(json.dumps({"candidate": candidate, "policy": asdict(policy)}), encoding="utf-8")
    completed = ProcessRunner().run(CommandSpec((sys.executable, "-B", str(Path(root) / "tools/issue_capture.py"),
                                                str(request), str(response)), max(1, seconds)))
    if completed.timed_out:
        raise TimeoutError("SOURCE_ACQUISITION_TIMEOUT")
    if not response.is_file():
        raise RuntimeError("SOURCE_ACQUISITION_FAILED: " + completed.stderr[-500:])
    value = json.loads(response.read_text(encoding="utf-8"))
    if value["status"] != "CAPTURED":
        raise ValueError(value.get("reason", "SOURCE_REJECTED"))
    return json.loads(report.cas.get_text(value["task_ref"]))
