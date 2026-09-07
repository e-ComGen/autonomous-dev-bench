"""Full repositories for native tools; bounded Python views for the existing ADCP contracts."""
from pathlib import Path
import base64
from .files import materialize, overlay, safe_path, IGNORED


class RepositoryWorkspace:
    def __init__(self, base_files, max_patch_bytes):
        self.base = base_files
        self.max_patch_bytes = max_patch_bytes

    def materialize(self, projection, destination):
        materialize(destination, overlay(self.base, projection))

    def read_candidate(self, projection, directory):
        directory = Path(directory)
        expected = overlay(self.base, projection)
        allowed = set(projection) - {"TASK.md", "public_tests.py"}
        result = dict(projection)
        changed_bytes = 0
        for relative, record in expected.items():
            path = directory / safe_path(relative)
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != directory.parent):
                raise ValueError("LINKED_CANDIDATE")
            if not path.is_file() or path.stat().st_size > 4194304:
                raise ValueError("DELETED_OR_OVERSIZED_CANDIDATE")
            payload = path.read_bytes()
            before = base64.b64decode(record["data"])
            if payload == before:
                continue
            if relative not in allowed:
                raise ValueError("PROTECTED_FILE_CHANGED: " + relative)
            changed_bytes += len(payload)
            if changed_bytes > self.max_patch_bytes:
                raise ValueError("PATCH_SIZE_LIMIT")
            result[relative] = payload.decode("utf-8")
        for path in directory.rglob("*"):
            relative = path.relative_to(directory)
            if set(relative.parts) & IGNORED:
                continue
            if path.is_symlink():
                raise ValueError("LINKED_CANDIDATE")
            if path.is_file() and relative.as_posix() not in expected:
                raise ValueError("UNDECLARED_NEW_FILE: " + relative.as_posix())
        return result
