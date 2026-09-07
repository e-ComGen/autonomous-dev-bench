"""Attach observed same-release CI evidence without claiming a paid ADCP comparison."""
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attach(root):
    root = Path(root).resolve()
    metadata_path = root / ".bench/release.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for relative, expected in metadata["files"].items():
        if sha(root / relative) != expected:
            raise ValueError("Release input changed after verification: " + relative)
    results = {}
    for platform in ("windows-latest", "ubuntu-latest"):
        directory = root / ".bench/validation-native" / ("native-evidence-" + platform)
        junit = ET.parse(directory / "tests.xml")
        counts = {"cases": len(list(junit.iter("testcase"))), "failures": len(list(junit.iter("failure"))),
                  "errors": len(list(junit.iter("error"))), "skipped": len(list(junit.iter("skipped")))}
        if counts["cases"] < 200 or counts["failures"] or counts["errors"]:
            raise ValueError("Native host regression did not pass")
        counts["passed"] = counts["cases"] - counts["skipped"]
        sdk = json.loads((directory / "native-process.json").read_text(encoding="utf-8"))
        issue = json.loads((directory / "native-issue.json").read_text(encoding="utf-8"))
        if (sdk["sdk_boot"]["status"] != "BOOTED" or sdk["sdk_session"] != "RETURNED"
                or not sdk.get("actual_tool_effect") or sdk["docker_invoked"] or sdk["paid_model_called"]):
            raise ValueError("SDK/tool acceptance evidence is missing")
        if (issue["status"] != "TASKS_QUALIFIED" or not issue["replay_checked"] or issue["empty_patch"] != "FAIL"
                or issue["reference_patch"] != "PASS" or issue["docker_invoked"] or issue["paid_model_called"]):
            raise ValueError("Real issue qualification evidence is missing")
        results[platform] = {"tests": counts, "native_sdk": sdk, "real_issue": issue}
    summary = {"source_commit": metadata["source_commit"], "backend": "native", "platforms": results,
        "paid_ab_executed": False, "private_adcp_end_to_end": "NOT_EXECUTED_IN_PUBLIC_CI",
        "os_sandbox": False, "system_install_or_reboot_performed": False}
    (root / ".bench/validation-native/VALIDATION.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    metadata["default_command"] = "ab"
    metadata["windows_backend"] = "native"
    metadata["files"] = {path.relative_to(root).as_posix(): sha(path)
        for path in sorted(root.rglob("*")) if path.is_file() and path != metadata_path}
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"source_commit": summary["source_commit"], "paid_ab_executed": False,
        "host_tests": {key: value["tests"] for key, value in results.items()},
        "native_tool_effects_checked": True, "real_issue_qualification_checked": True}, indent=2))


if __name__ == "__main__":
    attach(sys.argv[1])
