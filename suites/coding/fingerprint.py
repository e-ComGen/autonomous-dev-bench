"""Replay identities bind execution code as well as task/configuration data."""
from pathlib import Path
import hashlib
from .adcp_loading import ADCP_COMMIT


def implementation_fingerprint(root):
    root = Path(root)
    digest = hashlib.sha256()
    digest.update(ADCP_COMMIT.encode("ascii"))
    directories = ("suites/coding", "corpus/qualification", "corpus/discovery", "packages/benchmark_core/benchmark_core")
    for directory in directories:
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
    return "sha256:" + digest.hexdigest()
