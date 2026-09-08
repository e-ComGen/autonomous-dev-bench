"""Package a source overlay and complete native release without operator credentials."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
BASE = "747dfd15a909ff711cb2cf77c94ac46e81a55705"
BASE_ARCHIVE_SHA256 = "5603f52d8d17c41c40269103f36c909ea8e81e1f974597392ebc4edb9af0884b"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def safe_extract(archive, destination):
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:
            raise ValueError("Invalid base release")
        for member in source.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("Unsafe base release path")
            if path.name == ".env" or path.suffix in {".pyc", ".pyo"}:
                raise ValueError("Unexpected credential or bytecode in base release")
            source.extract(member, destination)


def main():
    archive = Path(sys.argv[1])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != BASE_ARCHIVE_SHA256:
        raise ValueError("Exact native release hash mismatch")
    stage = ROOT / "artifacts/autobenchmark"
    overlay = ROOT / "artifacts/source-fix"
    for directory in (stage, overlay):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    safe_extract(archive, stage)
    paths = [name.decode() for name in git("ls-files", "-z").split(b"\0") if name]
    changed = {name.decode() for name in git("diff", "--name-only", "-z", BASE, "HEAD").split(b"\0") if name}
    for name in paths:
        path = ROOT / name
        if path.name == ".env" or name.startswith(".bench/"):
            raise ValueError("Private operator files must never be tracked")
        if not path.is_file() or path.is_symlink():
            raise ValueError("Unsupported source payload")
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        if name in changed and not name.startswith(".github/"):
            target = overlay / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    validation = {"source_commit": git("rev-parse", "HEAD").strip().decode(), "baseline": BASE,
                  "paid_model_called": False, "full_ab_executed": False,
                  "files_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                   for name in sorted(changed & set(paths)) if not name.startswith(".github/")}}
    for directory in (stage, overlay):
        (directory / "SOURCE_VALIDATION.json").write_text(json.dumps(validation, indent=2))
    metadata = stage / ".bench/release.json"
    value = json.loads(metadata.read_text()) if metadata.exists() else {}
    value.update(source_commit=validation["source_commit"], files={path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(stage.rglob("*")) if path.is_file() and path != metadata})
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps(value, indent=2))
    print(json.dumps({"stage": str(stage), "overlay": str(overlay), **validation}, indent=2))


if __name__ == "__main__":
    main()
