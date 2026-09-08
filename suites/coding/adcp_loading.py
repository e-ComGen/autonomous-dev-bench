"""Verify and load the pinned real ADCP; never silently fall back to an older runtime."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

ADCP_COMMIT = "285702063815280398b95ba8696566259c8b5b34"
PREVIOUS_ADCP_COMMIT = "b9c933bd7727b86149da891c323a27cde5afc956"


def verify_distribution(distribution):
    distribution = Path(distribution)
    if distribution.is_symlink():
        raise ValueError("Unsafe ADCP distribution path")
    metadata_file = distribution / "SOURCE.json"
    if not metadata_file.is_file() or metadata_file.is_symlink():
        raise RuntimeError("ADCP_SOURCE_MISSING")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if metadata.get("commit") != ADCP_COMMIT:
        raise ValueError("ADCP runtime identity mismatch; run START.cmd to stage the pinned upgrade")
    files = metadata.get("files")
    required = {"packages/zone_development/contracts.py", "packages/zone_development/workspace.py",
                "packages/zone_development/snapshot_reader.py"}
    if not isinstance(files, dict) or not required <= set(files):
        raise ValueError("ADCP manifest omits required runtime source")
    for relative, expected in files.items():
        name = PurePosixPath(relative)
        if name.is_absolute() or '..' in name.parts or '\\' in relative:
            raise ValueError("Unsafe ADCP manifest path")
        path = distribution / relative
        if path.is_symlink() or not path.resolve().is_relative_to(distribution.resolve()):
            raise ValueError("Unsafe ADCP distribution path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("ADCP source integrity mismatch: " + relative)
    actual_python = {path.relative_to(distribution).as_posix() for path in distribution.rglob('*.py')}
    if actual_python - set(files):
        raise ValueError("ADCP distribution contains undeclared Python source")
    return metadata


def load_adcp(root):
    distribution = Path(root) / ".bench/adcp"
    verify_distribution(distribution)
    sys.path[:0] = [str(distribution), str(distribution / "packages/shared_contracts/src")]
    from packages.zone_development import ZoneDevelopmentRuntime
    return {"commit": ADCP_COMMIT, "runtime": ZoneDevelopmentRuntime.__module__ + "." + ZoneDevelopmentRuntime.__name__,
            "integration": "existing-v2-runtime-role-ports", "vnext_gateway_claimed": False,
            "source_snapshot_ceiling": 33554432}
