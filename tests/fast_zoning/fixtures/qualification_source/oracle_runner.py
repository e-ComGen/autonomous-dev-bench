"""Trusted isolated entrypoint: execute the bound external oracle, never a copy.

The sandbox protects files, not Python's in-memory verdict against malicious
candidate Python. This pilot does not claim an adversarial interpreter boundary.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


def main() -> int:
    oracle, expected_hash, candidate, entrypoint = sys.argv[1:]
    # Parent already canonicalized both paths under a retained sharing lock.
    # Resolving again asks Windows for ancestor access outside child grants.
    canonical = Path(oracle)
    with canonical.open("rb") as stream:
        opened_stat = os.fstat(stream.fileno())
        payload = stream.read()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError("ORACLE_IDENTITY_MISMATCH")
    # Emit identity before importing any subject-under-test code.
    print(json.dumps({"oracle_executed_path": str(canonical),
                      "oracle_executed_sha256": actual_hash,
                      "oracle_executed_file_identity": [opened_stat.st_dev, opened_stat.st_ino]}), flush=True)
    root = Path(candidate)
    sys.path.insert(0, str(root / "src"))
    sys.path.insert(1, str(root))
    namespace = {"__file__": str(canonical), "__name__": "__canonical_oracle__"}
    try:
        exec(compile(payload, str(canonical), "exec"), namespace)
        namespace[entrypoint]()
    except BaseException:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
