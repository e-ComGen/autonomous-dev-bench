from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import tools.product_readiness_harbor as readiness_harbor
from tools.product_readiness_harbor import _write_wheel_manifest
from tools.product_readiness_linux_campaign import (
    _assert_clean,
    _cleanup_legacy_self_generated_artifacts,
    _locked_task_pathspecs,
)
from tools.qualify_phase3c3_real_adcp_dsh import _configure_adcp_import_paths


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "autobench-test")
    _git(repo, "config", "user.email", "autobench@example.invalid")


def test_wsl_clean_check_ignores_only_crlf_normalization(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    tracked = repo / "tracked.txt"
    tracked.write_bytes(b"same-content\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "fixture")

    tracked.write_bytes(b"same-content\r\n")
    _assert_clean(repo)

    tracked.write_bytes(b"changed-content\r\n")
    with pytest.raises(RuntimeError, match="tracked changes"):
        _assert_clean(repo)

    _git(repo, "checkout", "--", "tracked.txt")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="untracked files"):
        _assert_clean(repo)


def test_clean_check_can_scope_large_corpus_to_locked_task_paths(tmp_path: Path) -> None:
    repo = tmp_path / "tasks-repo"
    _init_repo(repo)
    locked = repo / "tasks" / "locked-task"
    unrelated = repo / "tasks" / "unrelated-task"
    locked.mkdir(parents=True)
    unrelated.mkdir(parents=True)
    (locked / "task.yaml").write_text("instance_id: locked-task\n", encoding="utf-8")
    (unrelated / "task.yaml").write_text("instance_id: unrelated-task\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")

    pathspecs = ("tasks/locked-task",)
    (unrelated / "task.yaml").write_text("instance_id: changed-but-unused\n", encoding="utf-8")
    _assert_clean(repo, pathspecs=pathspecs)

    (locked / "task.yaml").write_text("instance_id: changed-locked\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="tracked changes"):
        _assert_clean(repo, pathspecs=pathspecs)

    _git(repo, "checkout", "--", "tasks/locked-task/task.yaml")
    (locked / "extra.txt").write_text("untracked locked input\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="untracked files"):
        _assert_clean(repo, pathspecs=pathspecs)


def test_locked_task_pathspecs_bind_to_plan_and_task_yaml(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks-repo"
    for task_id in ("a__a-1", "b__b-2"):
        task_dir = tasks_root / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text(f"instance_id: {task_id}\n", encoding="utf-8")
    plan = {"corpus": {"tasks": ["a__a-1", "b__b-2"]}}

    assert _locked_task_pathspecs(plan, tasks_root) == ("tasks/a__a-1", "tasks/b__b-2")

    (tasks_root / "tasks" / "b__b-2" / "task.yaml").unlink()
    with pytest.raises(RuntimeError, match="missing or malformed"):
        _locked_task_pathspecs(plan, tasks_root)


def test_legacy_self_generated_adcp_artifact_is_removed_before_pin_check(tmp_path: Path) -> None:
    root = tmp_path / "bench"
    legacy = root / "artifacts" / "phase3c-adcp" / "PHASE3C_ADCP_FAKE_HARBOR.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}\n", encoding="utf-8")

    _cleanup_legacy_self_generated_artifacts(root)

    assert not legacy.exists()
    assert not (root / "artifacts" / "phase3c-adcp").exists()


def test_adcp_harbor_evidence_is_written_to_campaign_workspace(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bench"
    workspace = tmp_path / "campaign"
    harbor_root = tmp_path / "harbor"
    captured: dict[str, str] = {}

    monkeypatch.setattr(readiness_harbor, "_prepare_task", lambda source, target: None)
    monkeypatch.setattr(readiness_harbor, "_common_script_prefix", lambda root, harbor_root: "")
    monkeypatch.setattr(readiness_harbor, "_linux_path", lambda path: str(path))

    def fake_bash(script: str, *, timeout: int = 1800) -> str:
        captured["script"] = script
        return "PASS"

    monkeypatch.setattr(readiness_harbor, "_bash", fake_bash)

    assert readiness_harbor.run_adcp_boundary_trial(root, workspace, harbor_root) == "PASS"
    expected = workspace / "artifacts" / "phase3c-adcp" / "PHASE3C_ADCP_FAKE_HARBOR.json"
    assert "--output" in captured["script"]
    assert str(expected) in captured["script"]
    assert str(root / "artifacts" / "phase3c-adcp") not in captured["script"]


def test_stock_wheel_manifest_recomputes_and_checks_pinned_digests(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    sdk = wheel_dir / "deepseek_harness_sdk-0.1.2rc1-py3-none-any.whl"
    runtime = wheel_dir / "deepseek_harness_runtime_bin-0.1.2rc1-py3-none-manylinux_2_28_x86_64.whl"
    sdk.write_bytes(b"sdk-wheel")
    runtime.write_bytes(b"runtime-wheel")

    lock = {
        "sdk": {
            "wheel": sdk.name,
            "sha256": hashlib.sha256(sdk.read_bytes()).hexdigest(),
        },
        "runtime": {
            "linux_x86_64_wheel": runtime.name,
            "linux_x86_64_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        },
    }
    lock_path = tmp_path / "DEEPSEEK_HARNESS.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    output = tmp_path / "DSH_WHEELS.json"

    manifest = _write_wheel_manifest(lock_path, wheel_dir, output)

    assert manifest["scope"] == "PHASE2_DSH_WHEEL_CLOSURE"
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    assert {entry["filename"] for entry in manifest["wheels"]} == {sdk.name, runtime.name}

    runtime.write_bytes(b"tampered-runtime-wheel")
    with pytest.raises(RuntimeError, match="wheel pin mismatch"):
        _write_wheel_manifest(lock_path, wheel_dir, output)


def test_real_adcp_qualifier_adds_src_layout_for_shared_contracts(tmp_path: Path) -> None:
    adcp = tmp_path / "adcp"
    shared_src = adcp / "packages" / "shared_contracts" / "src"
    package = shared_src / "shared_contracts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    original = list(sys.path)
    try:
        _configure_adcp_import_paths(adcp)
        assert sys.path[0] == str(shared_src)
        assert sys.path[1] == str(adcp)
    finally:
        sys.path[:] = original
