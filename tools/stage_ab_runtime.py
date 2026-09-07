"""Stage exact private ADCP Git bytes locally; never upload them to a public repository."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suites.coding.adcp_loading import ADCP_COMMIT, load_adcp


def stage(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        raise FileExistsError("ADCP staging target must be fresh")
    data = subprocess.run(["git", "-C", str(source), "archive", ADCP_COMMIT],
                          check=True, capture_output=True, timeout=60).stdout
    target.mkdir(parents=True)
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
            # Tests/examples are not production dependencies and do not belong in the operator package.
            if relative.parts[0] not in {"packages", "docs"} and member.name != "README.md":
                continue
            payload = archive.extractfile(member).read()
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            files[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    (target / "SOURCE.json").write_text(json.dumps({"commit": ADCP_COMMIT, "files": files}, indent=2), encoding="utf-8")
    print(json.dumps({"commit": ADCP_COMMIT, "staged_files": len(files)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    args = parser.parse_args()
    stage(args.source, ROOT / ".bench/adcp")
    print(json.dumps(load_adcp(ROOT)))
