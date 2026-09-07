"""Package only the discovery overlay; assert runtime, credentials and budgets did not change."""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = "ed022ac7fad8975eb3dd997c18a7948084ef5386"
PAYLOAD = (
    "corpus/discovery/search_plan.py", "corpus/discovery/pull_prefilter.py",
    "corpus/discovery/issue_queries.py", "corpus/discovery/automatic.py",
    "corpus/discovery/diagnostics.py", "suites/coding/issue_preparation.py",
    "tools/export_discovery.py", "EXPORT_DISCOVERY.cmd", "DISCOVERY_FIX.md",
    "tests/discovery/test_prefilter.py", "tests/discovery/test_sampling.py",
    "tests/discovery/test_diagnostics.py",
)
PROTECTED = ("AB.toml", ".env.example", "START.cmd", "RUN_NATIVE_ONCE.cmd",
             "tools/start_ready.py", "tools/launcher_credentials.py",
             "corpus/qualification/changes.py", "corpus/qualification/qualifier.py",
             "suites/coding/cycle.py", "suites/coding/issue_campaign.py")


def git(*arguments):
    return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True,
                          capture_output=True, timeout=60).stdout


def counts(path):
    document = ET.parse(path)
    cases = list(document.iter("testcase"))
    result = {"cases": len(cases), "failures": len(list(document.iter("failure"))),
              "errors": len(list(document.iter("error"))), "skipped": len(list(document.iter("skipped")))}
    result["passed"] = result["cases"] - result["failures"] - result["errors"] - result["skipped"]
    if result["cases"] < 260 or result["failures"] or result["errors"]:
        raise ValueError("FULL_HOST_SUITE_NOT_ACCEPTED")
    return result


def main():
    head = git("rev-parse", "HEAD").decode().strip()
    evidence = ROOT / "artifacts/discovery"
    evidence.mkdir(parents=True, exist_ok=True)
    for name in PROTECTED:
        if git("show", BASE + ":" + name) != git("show", "HEAD:" + name):
            raise ValueError("Protected responsibility changed: " + name)
    host = counts(ROOT / "artifacts/tests.xml")
    stage = ROOT / "artifacts/discovery-fix"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    hashes = {}
    for name in PAYLOAD:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = git("show", "HEAD:" + name)
        target.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    # Apply the actual payload to the previous shipped source, outside its .git.
    with tempfile.TemporaryDirectory(prefix="discovery patch with spaces ") as temporary:
        checkout = Path(temporary) / "benchmark"
        checkout.mkdir()
        with tarfile.open(fileobj=io.BytesIO(git("archive", BASE))) as archive:
            for member in archive:
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError("Unsafe baseline archive entry")
                if member.isfile():
                    target = checkout / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        for name in PAYLOAD:
            destination = checkout / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage / name, destination)
        environment = dict(os.environ)
        for name in ("GITHUB_TOKEN", "GH_TOKEN", "DEEPSEEK_API_KEY"):
            environment.pop(name, None)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        junit = evidence / "overlay-tests.xml"
        with (evidence / "overlay-tests.log").open("wb") as log:
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(junit)],
                                    cwd=checkout, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if result.returncode:
            print((evidence / "overlay-tests.log").read_text(encoding="utf-8", errors="replace")[-8000:])
            raise ValueError("APPLIED_OVERLAY_TESTS_FAILED")
        applied = counts(junit)
    metadata = {"source_commit": head, "baseline_commit": BASE, "platform": sys.platform,
                "host_tests": host, "applied_overlay_tests": applied, "path_with_spaces": True,
                "protected_files_unchanged": list(PROTECTED), "files_sha256": hashes,
                "paid_model_called": False, "full_ab_executed": False}
    (stage / "DISCOVERY_VALIDATION.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
