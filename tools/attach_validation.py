"""Attach machine-observed CI evidence without claiming a paid A/B result."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import xml.etree.ElementTree as ET


def main():
    stage, evidence = Path(sys.argv[1]), Path(sys.argv[2])
    report = {"paid_ab_executed": False, "host_tests": {}, "validation_source": "same-commit GitHub Actions"}
    for platform in ("ubuntu-latest", "windows-latest"):
        path = evidence / platform / "tests.xml"
        tree = ET.parse(path)
        cases = list(tree.iter("testcase"))
        counts = {"cases": len(cases), "failures": len(list(tree.iter("failure"))),
                  "errors": len(list(tree.iter("error"))), "skipped": len(list(tree.iter("skipped")))}
        if counts["cases"] < 200 or counts["failures"] or counts["errors"]:
            raise ValueError("Host suite evidence is incomplete or failed")
        counts["passed"] = counts["cases"] - counts["skipped"]
        report["host_tests"][platform] = counts
    native = json.loads((evidence / "native/native-boot.json").read_text())
    if native["receipt"] != {"status": "BOOTED", "model_called": False}:
        raise ValueError("Native boot evidence missing")
    report["native_boot"] = native
    transport = json.loads((evidence / "native/native-transport.json").read_text())
    if transport["status"] != "NATIVE_TRANSPORT_CHECKED" or transport["paid_provider_contacted"]:
        raise ValueError("Incorrect native fixture evidence")
    report["native_transport"] = transport
    issue = json.loads((evidence / "qualification/issue-qualification.json").read_text())
    if issue["status"] != "TASKS_QUALIFIED" or not issue["replay_checked"]:
        raise ValueError("Actual GitHub task qualification was not accepted")
    report["real_issue"] = {key: issue[key] for key in ("repository", "issue", "pull", "base", "fix", "replay_checked")}
    report["real_issue"].update(fail_to_pass=len(issue["qualification"]["fail_to_pass"]),
                               pass_to_pass=len(issue["qualification"]["pass_to_pass"]))
    metadata_path = stage / ".bench/release.json"
    metadata = json.loads(metadata_path.read_text())
    report["source_commit"] = metadata["source_commit"]
    # Existing inputs must still match the package that was executed on CI.
    for relative, expected in metadata["files"].items():
        if hashlib.sha256((stage / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Package input changed before evidence attachment")
    target = stage / ".bench/validation"
    target.mkdir(parents=True)
    (target / "VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for path in evidence.rglob("*.json"):
        destination = target / path.relative_to(evidence)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    metadata["files"] = {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in stage.rglob("*") if path.is_file() and path != metadata_path}
    metadata["default_command"] = "ab"
    metadata["task_source"] = "GITHUB_ISSUE_MERGED_PR"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
