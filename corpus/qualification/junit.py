"""Strict per-test observations. Missing, duplicate or skipped required cases cannot pass."""
import xml.etree.ElementTree as ET


def parse_junit(payload):
    if len(payload) > 8388608 or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("UNSAFE_JUNIT")
    root = ET.fromstring(payload)
    result = {}
    for case in root.iter("testcase"):
        identity = case.get("classname", "") + "::" + case.get("name", "")
        if not case.get("name") or identity in result:
            raise ValueError("AMBIGUOUS_JUNIT_TEST")
        outcomes = [name for name in ("failure", "error", "skipped") if case.find(name) is not None]
        if len(outcomes) > 1:
            raise ValueError("CONFLICTING_JUNIT_STATUS")
        result[identity] = {"failure": "FAIL", "error": "ERROR", "skipped": "SKIP"}.get(outcomes[0], "PASS") if outcomes else "PASS"
    if not result:
        raise ValueError("EMPTY_TEST_RUN")
    return result


def acceptance_sets(public, broken, repaired):
    if not public or any(value != "PASS" for value in public.values()):
        raise ValueError("PUBLIC_BASELINE_NOT_GREEN")
    if not repaired or any(value != "PASS" for value in repaired.values()):
        raise ValueError("REFERENCE_NOT_GREEN")
    if set(broken) != set(repaired) or any(value not in {"PASS", "FAIL"} for value in broken.values()):
        raise ValueError("INCOMPARABLE_BASE_REFERENCE_TESTS")
    failing = sorted(key for key in repaired if broken[key] == "FAIL")
    if not failing:
        raise ValueError("ISSUE_NOT_REPRODUCED")
    return {"fail_to_pass": failing, "pass_to_pass": sorted(public), "acceptance": sorted(repaired)}


def classify(actual, expected):
    if any(status == "ERROR" for status in actual.values()):
        return "EVALUATION_ERROR"
    if set(actual) != set(expected):
        return "EVALUATION_ERROR"
    return "PASS" if all(actual[key] == expected[key] == "PASS" for key in expected) else "FAIL"
