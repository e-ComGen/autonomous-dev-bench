"""Attach observed tests, speed and issue qualification to both exact delivery forms."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]


def test_counts(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failed = len(list(root.iter("failure")))
    errors = len(list(root.iter("error")))
    skipped = len(list(root.iter("skipped")))
    if not cases or failed or errors:
        raise ValueError("Nonpassing source qualification test report")
    return {"cases": len(cases), "passed": len(cases) - failed - errors - skipped,
            "failures": failed, "errors": errors, "skipped": skipped}


def main():
    current = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.strip()
    evidence = ROOT / "artifacts/acceptance"
    results = {}
    for platform in ("ubuntu-latest", "windows-latest"):
        directory = evidence / ("source-evidence-" + platform)
        counts = test_counts(directory / "source-tests.xml")
        speed = json.loads((directory / "source-speed.json").read_text())
        if speed["candidate"] != current or not speed["byte_identical"] or speed["live_model_called"]:
            raise ValueError("Speed evidence does not bind this commit")
        results[platform] = {"tests": counts, "acquisition_microbenchmark": speed}
    issue = json.loads((evidence / "native-source-issue" / "native-issue.json").read_text())
    if issue["empty_patch"] != "FAIL" or issue["reference_patch"] != "PASS" or not issue["replay_checked"] or issue["paid_model_called"]:
        raise ValueError("Real issue qualification controls were not observed")
    for name in ("autobenchmark", "source-fix"):
        stage = ROOT / "artifacts" / name
        target = stage / "validation-source"
        shutil.copytree(evidence, target, dirs_exist_ok=True)
        metadata = stage / "SOURCE_VALIDATION.json"
        validation = json.loads(metadata.read_text())
        if validation["source_commit"] != current:
            raise ValueError("Package and evidence commit mismatch")
        validation.update(observed_host=results, real_issue_qualification=issue,
            remaining={"large_source_limit_expansion": "PRIVATE_CI_DID_NOT_EXECUTE_NOT_ACTIVATED",
                       "paid_full_ab": "NOT_RUN", "hard_input_token_cap": None, "hard_dollar_cap": None})
        metadata.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    stage = ROOT / "artifacts/autobenchmark"
    metadata = stage / ".bench/release.json"
    value = json.loads(metadata.read_text())
    value["files"] = {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in stage.rglob("*") if path.is_file() and path != metadata}
    metadata.write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps({"source_commit": current, "tests": {key: item["tests"] for key, item in results.items()},
                      "real_issue_qualification": issue, "paid_full_ab": False}, indent=2))


if __name__ == "__main__":
    main()
