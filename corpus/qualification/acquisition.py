"""Parent-side deadline and visible progress over the established ProcessRunner and CAS."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
from uuid import uuid4
from benchmark_core.execution import CommandSpec, ProcessRunner
from .progress import heartbeat, read_progress


def acquire_bounded(root, candidate, policy, seconds, report):
    directory = report.directory / ("capture-" + uuid4().hex[:8])
    directory.mkdir()
    request, response = directory / "request.json", directory / "response.json"
    progress = directory / "progress.json"
    request.write_text(json.dumps({"candidate": candidate, "policy": asdict(policy)}), encoding="utf-8")
    with heartbeat(progress):
        completed = ProcessRunner().run(CommandSpec((sys.executable, "-B", str(Path(root) / "tools/issue_capture.py"),
                                                    str(request), str(response)), max(1, seconds)))
    record = read_progress(progress)
    (directory / "process.log").write_text(completed.stdout[-16000:] + completed.stderr[-16000:], encoding="utf-8")
    if completed.timed_out:
        raise TimeoutError(f"SOURCE_ACQUISITION_TIMEOUT: stage={record.get('stage', 'starting')}; elapsed={completed.wall_time_seconds:.1f}s")
    if not response.is_file():
        raise RuntimeError("SOURCE_ACQUISITION_FAILED: " + completed.stderr[-500:])
    value = json.loads(response.read_text(encoding="utf-8"))
    if value["status"] != "CAPTURED":
        raise ValueError(value.get("reason", "SOURCE_REJECTED"))
    print(f"  Source ready: {completed.wall_time_seconds:.1f}s", flush=True)
    return json.loads(report.cas.get_text(value["task_ref"]))
