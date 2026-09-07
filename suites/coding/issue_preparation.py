"""Real candidate-to-qualified-task pipeline; preserve reasons instead of a bare quota error."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import time
from benchmark_core.identity import canonical_json, Sha256Digest
from corpus.discovery.github import GitHubReader
from corpus.discovery.automatic import AutomaticIntake
from corpus.discovery.diagnostics import summarize, reason_code, top_reasons
from corpus.qualification.acquisition import acquire_bounded
from corpus.qualification.qualifier import qualify, IssueTask
from corpus.qualification.evaluator import PytestEvaluator
from corpus.qualification.selection import Selection
from cli.oneclick.report import atomic_write
from .fingerprint import implementation_fingerprint
from .backend import validate_environment


def save_lock(report, seed, settings, policy, selected):
    entries = []
    for task, prepared in selected:
        value = {key: item for key, item in prepared.items() if key not in {"evaluator", "workspace_adapter"}}
        value["task"] = asdict(task)
        entries.append(report.cas.put_text(canonical_json(value)))
    lock = {"schema": "autobench.github_selection/v1", "seed": seed, "tasks": entries,
            "settings_digest": str(Sha256Digest.of(asdict(settings))),
            "policy_digest": str(Sha256Digest.of(asdict(policy))),
            "implementation_digest": implementation_fingerprint(report.root)}
    lock["content_digest"] = str(Sha256Digest.of(lock))
    path = report.directory / "selection.json"
    atomic_write(path, json.dumps(lock, indent=2))
    return str(path.relative_to(report.root))


def restore_lock(path, root, docker, report, settings, policy):
    from corpus.qualification.files import code_view
    lock = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = lock.pop("content_digest")
    if str(Sha256Digest.of(lock)) != digest or lock["schema"] != "autobench.github_selection/v1":
        raise ValueError("SELECTION_LOCK_CORRUPT")
    if (lock["settings_digest"] != str(Sha256Digest.of(asdict(settings)))
            or lock["policy_digest"] != str(Sha256Digest.of(asdict(policy)))):
        raise ValueError("REPLAY_CONFIGURATION_CHANGED")
    if lock.get("implementation_digest") != implementation_fingerprint(root):
        raise ValueError("REPLAY_IMPLEMENTATION_CHANGED")
    selected = []
    for ref in lock["tasks"]:
        value = json.loads(report.cas.get_text(ref))
        task = IssueTask(**value.pop("task"))
        image = value["image"]
        validate_environment(docker, image)
        if code_view(value["captured"]["base_files"], policy.max_code_bytes) != value["captured"]["projection"]:
            raise ValueError("REPLAY_SOURCE_MISMATCH")
        value["evaluator"] = PytestEvaluator(docker, root, docker.scratch / task.task_id,
                                               value["captured"], image, settings.check_seconds)
        selected.append((task, value))
    if len(selected) != settings.tasks:
        raise ValueError("REPLAY_TASK_COUNT_MISMATCH")
    return lock["seed"], selected


def save_discovery(report, reader, intake, selection, rejected, requested, stop_reason):
    details = {"qualification_rejections": rejected, "intake_rejections": intake.rejected,
               "api_requests": reader.requests, "project_deficits": selection.deficits()}
    summary = summarize(details, requested=requested, qualified=len(selection.selected),
                        stop_reason=stop_reason, counts=intake.counts, searches=intake.searches)
    summary["details_ref"] = report.cas.put_text(canonical_json(details))
    atomic_write(report.directory / "discovery.json", json.dumps(summary, indent=2))
    return summary


def prepare(root, docker, report, settings, policy, seed):
    deadline = time.monotonic() + policy.prepare_seconds
    reader = GitHubReader(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "", report.cas, policy)
    reader.deadline = min(reader.deadline, deadline)
    intake = AutomaticIntake(reader, policy, seed)
    intake.deadline = deadline
    selection = Selection(policy, settings.tasks)
    rejected, terminal = [], None
    print("Discovery: test-aware-v2; metadata prefilter, then unchanged executable qualification", flush=True)
    try:
        for candidate in intake.candidates():
            if time.monotonic() >= deadline:
                raise TimeoutError("PREPARATION_BUDGET_EXHAUSTED")
            name = candidate["repository"]
            print(f"Checking {name}, issue #{candidate['issues'][0]['number']} ...", flush=True)
            stage = "acquisition"
            try:
                task = acquire_bounded(root, candidate, policy, min(policy.fetch_seconds, deadline - time.monotonic()), report)
                if not selection.wants(name, task["classification"]["scale"]):
                    raise ValueError("PROJECT_QUOTA_FILTER")
                stage = "qualification"
                recipe, prepared = qualify(root, docker, task, policy, settings, seed, deadline)
                if selection.add(recipe, prepared):
                    print(f"Qualified: {name} / #{candidate['issues'][0]['number']}", flush=True)
            except (OSError, ValueError, RuntimeError) as error:
                rejected.append({"repository": name, "pull": candidate["pull_number"],
                                 "stage": stage, "reason": str(error)[:2000]})
                print("Rejected: " + reason_code(error), flush=True)
            save_discovery(report, reader, intake, selection, rejected, settings.tasks, "IN_PROGRESS")
            if selection.complete:
                break
    except (OSError, ValueError, RuntimeError) as error:
        terminal = reason_code(error)
        raise
    except KeyboardInterrupt:
        terminal = "CANCELLED"
        raise
    finally:
        stop = "QUOTA_MET" if selection.complete else terminal or intake.stop_reason
        summary = save_discovery(report, reader, intake, selection, rejected, settings.tasks, stop)
        print(f"Discovery: qualified={len(selection.selected)}/{settings.tasks}; "
              f"repositories={intake.counts['repositories_inspected']}; "
              f"pulls={intake.counts['pulls_inspected']}; downloads={intake.counts['candidates_emitted']}", flush=True)
        if not selection.complete:
            print("Rejection reasons: " + top_reasons(summary), flush=True)
    if not selection.complete:
        raise ValueError("QUALIFIED_TASK_QUOTA_NOT_MET: " + top_reasons(summary) + "; see discovery.json")
    return selection.selected
