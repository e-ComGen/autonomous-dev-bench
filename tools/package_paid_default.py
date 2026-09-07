"""Build a narrow overlay and complete release from the exact prior public artifact."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE_DIGEST = "5603f52d8d17c41c40269103f36c909ea8e81e1f974597392ebc4edb9af0884b"
PAYLOAD = ("START.cmd", "RUN_NATIVE_ONCE.cmd", "tools/start_ready.py", "tools/launcher_credentials.py",
           "tools/launch.py", "tools/prepare_ab.py", ".env.example", ".gitignore", ".ignore", "LAUNCH_FIX.md",
           "tests/oneclick/test_credentials.py", "tests/oneclick/test_start_ready_cli.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(base_path):
    base_path = Path(base_path)
    if digest(base_path) != BASE_DIGEST:
        raise ValueError("Base release identity mismatch")
    artifacts = ROOT / "artifacts"
    stage, overlay = artifacts / "autobenchmark", artifacts / "paid-default-fix"
    if stage.exists() or overlay.exists():
        raise FileExistsError("Release output must be fresh")
    with zipfile.ZipFile(base_path) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or ":" in entry.filename or path.name == ".env"
                    or ((entry.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("Unsafe or credential-bearing base release member")
            if entry.is_dir():
                continue
            target = stage.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
    metadata_path = stage / ".bench/release.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for relative, expected in metadata["files"].items():
        if digest(stage / relative) != expected:
            raise ValueError("Base member identity mismatch: " + relative)
    for relative in PAYLOAD:
        for destination in (stage, overlay):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    cases = list(ET.parse(artifacts / "tests.xml").iter("testcase"))
    counts = {"cases": len(cases),
              "failures": sum(case.find("failure") is not None for case in cases),
              "errors": sum(case.find("error") is not None for case in cases),
              "skipped": sum(case.find("skipped") is not None for case in cases)}
    if counts["cases"] < 260 or counts["failures"] or counts["errors"]:
        raise ValueError("Full host test gate did not pass")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    evidence = {"source_commit": commit, "platform": sys.platform, "host_tests": counts,
                "paid_ab_executed": False, "scope": "launcher paid-default change",
                "base_artifact_sha256": BASE_DIGEST, "existing_dotenv_modified": False}
    for destination in (stage / ".bench/validation-paid-default", overlay / ".bench/validation-paid-default"):
        destination.mkdir(parents=True)
        (destination / "VALIDATION.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        shutil.copyfile(artifacts / "tests.xml", destination / "tests.xml")
    metadata["base_source_commit"] = metadata.get("source_commit")
    metadata["source_commit"] = commit
    metadata["paid_ab_default"] = True
    metadata["files"] = {path.relative_to(stage).as_posix(): digest(path)
                         for path in sorted(stage.rglob("*")) if path.is_file() and path != metadata_path}
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    package(sys.argv[1])
