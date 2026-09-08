"""Qualify before enrollment; reference and failed controls are never agent inputs."""
from dataclasses import dataclass
import json
import random
import time
from benchmark_core.identity import Sha256Digest
from .files import text, is_pytest_module
from .junit import acceptance_sets
from .recipes import build_project_image
from .evaluator import PytestEvaluator


@dataclass(frozen=True)
class IssueTask:
    task_id: str
    project_id: str
    description: str


def qualify(root, docker, captured, policy, settings, seed, deadline):
    # Keep every protected test asset in the overlay, but execute Python test modules only.
    hidden = {"kind": "acceptance", "paths": sorted(path for path in captured["test_overlay"] if is_pytest_module(path))}
    if not hidden["paths"]:
        raise ValueError("ACCEPTANCE_TEST_MODULES_MISSING")
    image, recipe = build_project_image(docker, captured, policy, deadline)
    candidate = captured["candidate"]
    issue = candidate["issues"][0]
    issue_task = IssueTask("issue-" + captured["identity"].split(":")[-1][:24], candidate["repository"],
                           issue["title"] + "\n\n" + issue["body"])
    if len(issue_task.description.encode()) > 32768:
        raise ValueError("ISSUE_STATEMENT_TOO_LARGE")
    paths = list(recipe["public_candidates"])
    random.Random(seed).shuffle(paths)
    public = {"kind": "public", "paths": sorted(paths[:policy.public_test_files])}
    evaluator = PytestEvaluator(docker, root, docker.scratch / issue_task.task_id, captured, image, settings.check_seconds)
    evaluator.deadline = deadline
    baseline = captured["projection"]
    fixed = {**baseline, **{path: text(value) for path, value in captured["fix_code"].items()}}
    samples = []
    for repetition in range(policy.qualification_repeats):
        print(f"Qualification: baseline public tests; repetition={repetition + 1}/{policy.qualification_repeats}", flush=True)
        public_results = evaluator.observe(baseline, public)
        if samples and public_results != samples[0][0]:
            raise ValueError("FLAKY_QUALIFICATION")
        if not public_results or any(value != "PASS" for value in public_results.values()):
            raise ValueError("PUBLIC_BASELINE_NOT_GREEN")
        print("Qualification: reproduce issue and verify reference", flush=True)
        broken_results = evaluator.observe(baseline, hidden)
        fixed_results = evaluator.observe(fixed, hidden)
        sets = acceptance_sets(public_results, broken_results, fixed_results)
        fixed_public = evaluator.observe(fixed, public)
        if public_results != fixed_public:
            raise ValueError("REFERENCE_REGRESSION")
        samples.append((public_results, broken_results, fixed_results, fixed_public))
    if any(sample != samples[0] for sample in samples[1:]):
        raise ValueError("FLAKY_QUALIFICATION")
    public_results, broken_results, fixed_results, fixed_public = samples[0]
    full_check = {"kind": "acceptance", "paths": sorted(set(hidden["paths"]) | set(public["paths"]))}
    all_fixed = evaluator.observe(fixed, full_check)
    if not all(value == "PASS" for value in all_fixed.values()):
        raise ValueError("REFERENCE_COMBINED_FAILURE")
    files = dict(baseline)
    if "TASK.md" in captured["base_files"] or "public_tests.py" in captured["base_files"]:
        raise ValueError("BENCHMARK_PUBLIC_FILE_COLLISION")
    files["TASK.md"] = issue_task.description + "\n\nRun existing public tests: python -B public_tests.py\n"
    files["public_tests.py"] = ("import subprocess, sys, tempfile, os\n"
        "raise SystemExit(subprocess.call([sys.executable, '-B', '-m', 'pytest', '-q', '-o', 'addopts=', "
        "'-o', 'cache_dir=' + os.path.join(tempfile.gettempdir(), 'pytest-cache'), "
        + ", ".join(repr(value) for value in public["paths"]) + "]))\n")
    evaluator.deadline = None
    return issue_task, {"files": files, "checks": full_check, "expected": all_fixed,
        "public_checks": public, "public_expected": public_results, "captured": captured, "image": image,
        "evaluator": evaluator, "qualification": {**sets, "repeats": policy.qualification_repeats,
        "base_source_digest": captured["base_source_digest"], "image_id": image, "recipe": recipe,
        "test_payload_digest": str(Sha256Digest.of(captured["test_overlay"]))}}
