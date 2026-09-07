"""Atomically stage exact private ADCP bytes; no half-installed runtime on interruption."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suites.coding.adcp_loading import ADCP_COMMIT, load_adcp


def stage(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        raise FileExistsError("ADCP staging target must be fresh")
    data = subprocess.run(["git", "-C", str(source), "archive", ADCP_COMMIT],
                          check=True, capture_output=True, timeout=60).stdout
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".adcp-stage-", dir=target.parent))
    try:
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                relative = Path(member.name)
                if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
                    raise ValueError("Unsafe ADCP source member")
                if not member.isfile():
                    if not member.isdir():
                        raise ValueError("ADCP distribution does not accept linked source")
                    continue
                if relative.parts[0] not in {"packages", "docs"} and member.name != "README.md":
                    continue
                payload = archive.extractfile(member).read()
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                files[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
        (temporary / "SOURCE.json").write_text(json.dumps({"commit": ADCP_COMMIT, "files": files}, indent=2), encoding="utf-8")
        os.rename(temporary, target)
        print(json.dumps({"commit": ADCP_COMMIT, "staged_files": len(files)}))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    args = parser.parse_args()
    stage(args.source, ROOT / ".bench/adcp")
    print(json.dumps(load_adcp(ROOT)))
