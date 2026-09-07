"""Small operator summaries backed by the existing CAS, not new evidence authority."""
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
        self.root = root
        self.command = command
        self.directory = root / ".bench/runs" / uuid4().hex
        self.directory.mkdir(parents=True)
        self.cas = FileSystemCAS(root / ".bench/cas")

    def save(self, result: dict) -> Path:
        result = {**result, "schema": "autobench.operator_report/v1", "command": self.command,
                  "authoritative": False, "live_model_called": False}
        text = canonical_json(result)
        if len(text.encode("utf-8")) > 131072:
            raise ValueError("Operator report exceeds 128 KiB; put details in CAS")
        reference = self.cas.put_text(text)
        path = self.directory / "summary.json"
        atomic_write(path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        pointer = {"status": result.get("status"), "command": self.command,
                   "report": str(path.relative_to(self.root)), "cas_ref": reference}
        atomic_write(self.root / ".bench/latest.json", json.dumps(pointer, indent=2) + "\n")
        print(f"{result.get('status', 'UNKNOWN')}: {self.command}")
        print(f"Summary: {path.relative_to(self.root)}")
        print("Live model calls: 0. Coding quality score: not measured.")
        return path
