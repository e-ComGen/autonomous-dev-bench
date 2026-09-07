"""Compact operator output; complete evidence lives in the existing digest-verifying CAS."""
from pathlib import Path
import json
import os
import tempfile
from uuid import uuid4
from benchmark_core.cas import FileSystemCAS
from benchmark_core.identity import canonical_json


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Report:
    def __init__(self, root: Path, command: str):
        self.root, self.command = root, command
        self.directory = root / ".bench/runs" / uuid4().hex
        self.directory.mkdir(parents=True)
        self.cas = FileSystemCAS(root / ".bench/cas")

    def save(self, result: dict) -> Path:
        value = {**result, "schema": "autobench.operator_report/v1", "command": self.command, "authoritative": False}
        value.setdefault("live_model_called", False)
        full_ref = self.cas.put_text(canonical_json(value))
        for key in ("rows", "order", "qualified_tasks", "rejections"):
            if key in value and len(canonical_json(value[key]).encode("utf-8")) > 16384:
                value[key + "_ref"] = self.cas.put_text(canonical_json(value[key]))
                value[key + "_count"] = len(value[key])
                del value[key]
        text = canonical_json(value)
        if len(text.encode("utf-8")) > 131072:
            raise ValueError("Operator report exceeds 128 KiB; put details in CAS")
        path = self.directory / "summary.json"
        atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        pointer = {"status": value.get("status"), "command": self.command,
                   "report": str(path.relative_to(self.root)), "cas_ref": full_ref}
        atomic_write(self.root / ".bench/latest.json", json.dumps(pointer, indent=2) + "\n")
        if self.command in {"ab", "ab-preflight", "qualify"}:
            self._readable(result)
        print(f"{value.get('status', 'UNKNOWN')}: {self.command}")
        print(f"Summary: {path.relative_to(self.root)}")
        print(f"Live model called: {bool(value['live_model_called'])}; completed episodes: {len(result.get('rows', []))}")
        return path

    def _readable(self, result):
        lines = ["# Coding A/B", "", "Status: " + str(result.get("status")), "",
                 "Seed: " + str(result.get("seed")), "", "| Arm | Solved | Episodes |", "| --- | ---: | ---: |"]
        for name, arm in result.get("comparison", {}).items():
            lines.append(f"| {name} | {arm['solved']} | {arm['episodes']} |")
        lines.extend(("", "Costs are not priced. Unknown usage is not zero.",
                      "Functional test acceptance is not a universal coding-quality score."))
        if result.get("reason"):
            lines.extend(("", "Reason: " + str(result["reason"])))
        atomic_write(self.directory / "RESULT.md", "\n".join(lines) + "\n")
