"""Load a separately pinned real ADCP distribution, never a replacement loop."""
from pathlib import Path
import hashlib
import json
import sys

ADCP_COMMIT = "b9c933bd7727b86149da891c323a27cde5afc956"


def load_adcp(root):
    distribution = Path(root) / ".bench/adcp"
    metadata_file = distribution / "SOURCE.json"
    if not metadata_file.is_file():
        raise RuntimeError("ADCP_SOURCE_MISSING: use the complete private A/B release")
    metadata = json.loads(metadata_file.read_text())
    if metadata.get("commit") != ADCP_COMMIT:
        raise ValueError("ADCP runtime identity mismatch; no silent version fallback")
    for relative, expected in metadata["files"].items():
        path = distribution / relative
        if path.is_symlink() or not path.resolve().is_relative_to(distribution.resolve()):
            raise ValueError("Unsafe ADCP distribution path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("ADCP source integrity mismatch: " + relative)
    sys.path[:0] = [str(distribution), str(distribution / "packages/shared_contracts/src")]
    from packages.zone_development import ZoneDevelopmentRuntime
    return {"commit": ADCP_COMMIT, "runtime": ZoneDevelopmentRuntime.__module__ + "." + ZoneDevelopmentRuntime.__name__,
            "integration": "existing-v2-runtime-role-ports", "vnext_gateway_claimed": False}
