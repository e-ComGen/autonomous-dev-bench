"""Overlay a verified prior release; no user credentials enter public build artifacts."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "bdcff037c136c248a0025a24b6e81a5138962a6f"
BASE_SHA256 = "20f354fdf49cf0c1923fa169d6feb98389c91ccb34ba111d2158393fb20dc224"
PAYLOAD = ("START.cmd", "RUN_NATIVE_ONCE.cmd", "LAUNCH_FIX.md", ".env.example", ".gitignore",
           "tools/start_ready.py", "tools/launcher_credentials.py", "tools/launch.py", "tools/prepare_ab.py",
           "tests/oneclick/test_credentials.py", "tests/oneclick/test_start_ready_cli.py")


def main(archive_path):
    path = Path(archive_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError("BASE_ARCHIVE_HASH_MISMATCH")
    destination = ROOT / "artifacts/autobenchmark"
    patch = ROOT / "artifacts/launcher-fix"
    destination.mkdir(parents=True, exist_ok=False)
    patch.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 200000000:
            raise ValueError("BASE_ARCHIVE_SIZE_LIMIT")
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
                raise ValueError("UNSAFE_BASE_ARCHIVE")
            if info.is_dir():
                continue
            if relative.name == ".env":
                raise ValueError("CREDENTIALS_MUST_NOT_BE_IN_RELEASE")
            target = destination / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    for relative in PAYLOAD:
        for base in (destination, patch):
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    # Context search must not sweep operator secrets into an agent prompt.
    ignore = destination / ".ignore"
    with ignore.open("a", encoding="utf-8") as stream:
        stream.write("\n.env\n.env.*\n")
    metadata_path = destination / ".bench/release.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    metadata.update(source_commit=head, benchmark_base_commit=BASE_COMMIT, launcher_hotfix="no-input-v1")
    metadata["files"] = {file.relative_to(destination).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                         for file in sorted(destination.rglob("*")) if file.is_file() and file != metadata_path}
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    receipt = {"source_commit": head, "benchmark_base_commit": BASE_COMMIT, "payload": list(PAYLOAD),
               "changes": "Launcher only; existing native backend and ADCP pin unchanged",
               "paid_ab_executed": False, "user_credentials_included": False}
    (patch / "PATCH_ID.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
