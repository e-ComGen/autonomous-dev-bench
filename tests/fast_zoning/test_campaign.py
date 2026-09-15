from pathlib import Path
import json

import pytest

from benchmark_core.fast_zoning.gitops import apply_patch, capture_patch, clone_snapshot, git, verify_source
from benchmark_core.fast_zoning.manifest import InvalidManifest
from benchmark_core.fast_zoning.manifest import plan_digest
from benchmark_core.fast_zoning.runner import execute_pair, plan_campaign


def test_fresh_copies_have_independent_worktrees_and_no_existing_destination(source_repo, tmp_path):
    a = clone_snapshot(source_repo["repo"], tmp_path / "A", source_repo["buggy_head"], source_repo["buggy_tree"])
    b = clone_snapshot(source_repo["repo"], tmp_path / "B", source_repo["buggy_head"], source_repo["buggy_tree"])
    (a / "logic.py").write_text("changed only A\n")
    assert (b / "logic.py").read_text() == "value = 0\n"
    verify_source(b, source_repo["buggy_head"], source_repo["buggy_tree"])
    with pytest.raises(ValueError, match="exists"):
        clone_snapshot(source_repo["repo"], a, source_repo["buggy_head"], source_repo["buggy_tree"])


def test_complete_patch_replays_modified_untracked_deleted_renamed_and_binary(source_repo, tmp_path):
    source = Path(source_repo["repo"])
    (source / "logic.py").write_text("value = 1\n")
    (source / "delete.txt").unlink()
    (source / "old.txt").rename(source / "renamed.txt")
    (source / "added.txt").write_text("new evidence\n")
    (source / "binary.bin").write_bytes(bytes(range(256)))
    index_before = git(source, "diff", "--cached")
    evidence = tmp_path / "evidence"
    capture = capture_patch(source, source_repo["buggy_head"], evidence)
    assert capture["patch_produced"] is True
    assert capture["patch_size"] == (evidence / "patch.diff").stat().st_size
    assert set(capture["changed_files"]) == {"logic.py", "delete.txt", "renamed.txt", "added.txt", "binary.bin"}
    assert any(row["status"].startswith("R") for row in capture["changes"])
    assert git(source, "diff", "--cached") == index_before
    fresh = clone_snapshot(source, tmp_path / "replay", source_repo["buggy_head"], source_repo["buggy_tree"])
    apply_patch(fresh, evidence / "patch.diff")
    assert (fresh / "logic.py").read_text() == "value = 1\n"
    assert not (fresh / "delete.txt").exists()
    assert not (fresh / "old.txt").exists()
    assert (fresh / "renamed.txt").read_text() == "rename evidence\n"
    assert (fresh / "binary.bin").read_bytes() == bytes(range(256))
    assert (fresh / "added.txt").read_text() == "new evidence\n"


def test_ignored_candidate_files_are_captured_too(source_repo, tmp_path):
    source = Path(source_repo["repo"])
    (source / ".gitignore").write_text("*.cache\n")
    (source / "new.cache").write_bytes(b"candidate ignored contents")
    evidence = tmp_path / "evidence"
    capture = capture_patch(source, source_repo["buggy_head"], evidence)
    assert "new.cache" in capture["changed_files"]
    fresh = clone_snapshot(source, tmp_path / "replay", source_repo["buggy_head"], source_repo["buggy_tree"])
    apply_patch(fresh, evidence / "patch.diff")
    assert (fresh / "new.cache").read_bytes() == b"candidate ignored contents"


def fake_executor(calls, fail_first=False):
    def execute(argv, cwd, stdout_path, stderr_path, env):
        calls.append({"argv": argv, "cwd": cwd, "environment": env})
        if fail_first and len(calls) == 1:
            raise OSError("offline simulated infrastructure failure")
        (Path(cwd) / "logic.py").write_text("value = 1\n")
        events = [{"type": "message_end", "message": {"role": "assistant", "usage": {"input": 2, "output": 1, "totalTokens": 3}}},
                  {"type": "agent_end", "isTerminal": True}]
        Path(stdout_path).write_text("\n".join(json.dumps(row) for row in events) + "\n")
        Path(stderr_path).write_text("")
        return {"exit_code": 0, "model_wall_time": 1.0}
    return execute


def test_durable_plan_binds_same_evaluator_and_exact_execution_configuration(task_manifest, tmp_path):
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    saved = json.loads((Path(plan["pair_dir"]) / "plan.json").read_text())
    assert saved["run_order"] == plan["run_order"]
    assert saved["arms"]["A"]["evaluation_plan_digest"] == saved["arms"]["B"]["evaluation_plan_digest"] == saved["evaluation_plan_digest"]
    a, b = saved["arms"]["A"], saved["arms"]["B"]
    assert a["workspace"] != b["workspace"]
    args_a, args_b = list(a["argv"]), list(b["argv"])
    args_a[2] = args_b[2] = "WORKSPACE"
    args_a[-1] = args_b[-1] = "@PACKET"
    assert args_a == args_b
    assert args_a[3:] == ["--mode", "json", "--no-session", "--model", "alibaba-token-plan/deepseek-v4-pro",
                           "--auto-approve", "--tools", "read,edit,write", "--max-time", "10m", "@PACKET"]
    with pytest.raises(FileExistsError):
        plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")


def test_execution_requires_authorization_before_any_executor(task_manifest, tmp_path):
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    calls = []
    with pytest.raises(PermissionError):
        execute_pair(plan["pair_dir"], executor=fake_executor(calls))
    assert calls == []


def test_saved_model_envelopes_share_instructions_and_task_without_hidden_hints(task_manifest, tmp_path):
    from importlib.resources import files
    data = json.loads(task_manifest.read_text())
    data['evaluator_only'] = {'forbidden_snippets': ['PRIVATE ROOT CAUSE DO NOT EXPOSE']}
    task_manifest.write_text(json.dumps(data))
    plan = plan_campaign(task_manifest, tmp_path / 'campaign', 'pair-001')
    scaffold = files('benchmark_core.fast_zoning').joinpath('instructions.md').read_bytes()
    shared = scaffold + b'\n# Task\n\n' + data['task_text'].encode() + b'\n\n# Context\n\n'
    for arm in ('A','B'):
        model_packet = Path(plan['arms'][arm]['packet_path']).read_bytes()
        original_context = Path(data['contexts'][arm]['packet_path']).read_bytes()
        assert model_packet == shared + original_context
        assert b'PRIVATE ROOT CAUSE DO NOT EXPOSE' not in model_packet


def test_each_arm_executes_once_even_when_first_has_infrastructure_failure(task_manifest, tmp_path):
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    calls = []
    result = execute_pair(plan["pair_dir"], authorized=True, executor=fake_executor(calls, fail_first=True))
    assert len(calls) == 2
    assert [Path(row["cwd"]).parent.name for row in calls] == plan["run_order"]
    assert calls[0]["environment"] == calls[1]["environment"]
    assert result["status"] == "INFRA_FAILURE"
    for arm in ("A", "B"):
        arm_dir = Path(plan["pair_dir"]) / arm
        assert json.loads((arm_dir / "metrics.json").read_text())["retries"] == 0
        assert (arm_dir / "raw.jsonl").exists()
        assert (arm_dir / "stderr.log").exists()
    first = json.loads((Path(plan["pair_dir"]) / plan["run_order"][0] / "metrics.json").read_text())
    second = json.loads((Path(plan["pair_dir"]) / plan["run_order"][1] / "metrics.json").read_text())
    assert first["model_executed"] is False
    assert second["model_executed"] is True
    with pytest.raises((FileExistsError, ValueError)):
        execute_pair(plan["pair_dir"], authorized=True, executor=fake_executor(calls))
    assert len(calls) == 2


def test_frozen_plan_tamper_blocks_all_model_calls(task_manifest, tmp_path):
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    path = Path(plan["pair_dir"]) / "plan.json"
    data = json.loads(path.read_text())
    data["run_order"] = list(reversed(data["run_order"]))
    path.write_text(json.dumps(data))
    calls = []
    with pytest.raises(InvalidManifest, match="changed"):
        execute_pair(plan["pair_dir"], authorized=True, executor=fake_executor(calls))
    assert calls == []


def test_cli_validate_and_dry_run_never_invoke_omp(task_manifest, tmp_path, monkeypatch, capsys):
    from cli.fast_zoning import main
    import benchmark_core.fast_zoning.runner as runner
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run attempted model execution")
    monkeypatch.setattr(runner, "_execute", forbidden)
    original_run = runner.subprocess.run
    def no_omp(argv, *args, **kwargs):
        assert "omp" not in Path(argv[0]).name.lower(), "dry-run must not even probe OMP version"
        return original_run(argv, *args, **kwargs)
    monkeypatch.setattr(runner.subprocess, "run", no_omp)
    assert main(["campaign", "validate", str(task_manifest)]) == 0
    assert json.loads(capsys.readouterr().out)["TASK_STATUS"] == "VALIDATED"
    assert main(["campaign", "plan", str(task_manifest), "--campaign-dir", str(tmp_path / "campaign"),
                 "--pair-run-id", "pair-001", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert main(["campaign", "execute", plan["pair_dir"], "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["MODEL_EXECUTED"] is False
    assert not (Path(plan["pair_dir"]) / "execution.claim").exists()
    with pytest.raises(SystemExit) as exc:
        main(["campaign", "execute", plan["pair_dir"]])
    assert exc.value.code == 2


def test_cli_invalid_manifest_persists_failure(task_manifest, tmp_path, capsys):
    from cli.fast_zoning import main
    data = json.loads(task_manifest.read_text())
    data["task_hash"] = "0" * 64
    task_manifest.write_text(json.dumps(data))
    output = tmp_path / "invalid.json"
    assert main(["campaign", "validate", str(task_manifest), "--output", str(output)]) == 2
    assert json.loads(output.read_text())["TASK_STATUS"] == "INVALID_MANIFEST"
    assert main(["campaign", "plan", str(task_manifest), "--campaign-dir", str(tmp_path / "campaign"),
                 "--pair-run-id", "pair-001"]) == 2
    state = json.loads((tmp_path / "campaign" / "invalid" / "pair-001" / "state.json").read_text())
    assert state["status"] == "INVALID_MANIFEST"


def test_evaluator_launch_error_is_not_an_invalid_candidate_patch(task_manifest, tmp_path):
    data = json.loads(task_manifest.read_text())
    data["evaluation_plan"]["evaluators"][0]["command"] = [str(tmp_path / "does-not-exist.exe"), "{artifact0}"]
    data["evaluation_plan_digest"] = plan_digest(data["evaluation_plan"])
    task_manifest.write_text(json.dumps(data))
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    calls = []
    result = execute_pair(plan["pair_dir"], authorized=True, executor=fake_executor(calls))
    assert len(calls) == 2
    for arm in ("A", "B"):
        metrics = json.loads((Path(plan["pair_dir"]) / arm / "metrics.json").read_text())
        assert metrics["existing_suite"] == "ERROR"
        assert metrics["semantic_success"] != "YES"
        assert metrics["repair_class"] != "INVALID_PATCH"
    assert result["status"] == "INFRA_FAILURE"


@pytest.mark.parametrize("tamper", ["packet", "evaluator"])
def test_between_arm_tamper_prevents_second_model_call(task_manifest, tmp_path, tamper):
    plan = plan_campaign(task_manifest, tmp_path / "campaign", "pair-001")
    calls = []
    execute = fake_executor(calls)
    def tampering_executor(*args):
        result = execute(*args)
        if tamper == "packet":
            path = Path(plan["arms"][plan["run_order"][1]]["packet_path"])
        else:
            data = json.loads(task_manifest.read_text())
            path = Path(data["evaluation_plan"]["evaluators"][0]["artifacts"][0]["path"])
        path.write_text("tampered")
        return result
    try:
        execute_pair(plan["pair_dir"], authorized=True, executor=tampering_executor)
    except InvalidManifest:
        pass
    assert len(calls) == 1
    state = json.loads((Path(plan["pair_dir"]) / "state.json").read_text())
    assert state["status"] in {"INVALID_MANIFEST", "INFRA_FAILURE"}


def test_cli_summary_includes_ready_state_without_chat_history(task_manifest, tmp_path, capsys):
    from cli.fast_zoning import main
    campaign = tmp_path / "campaign"
    plan = plan_campaign(task_manifest, campaign, "pair-001")
    # Candidate-created similarly named files cannot impersonate campaign state.
    (Path(plan["arms"]["A"]["workspace"]) / "state.json").write_text('{"status":"COMPLETED"}')
    (Path(plan["arms"]["A"]["workspace"]) / "paired-summary.json").write_text('{"status":"COMPLETED"}')
    assert main(["campaign", "summarize", str(campaign)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["pairs_incomplete"] == 1
    assert summary["pairs_valid"] == 0
    assert json.loads((campaign / "campaign-summary.json").read_text()) == summary
