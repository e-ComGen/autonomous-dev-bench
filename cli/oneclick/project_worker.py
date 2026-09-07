"""One bounded project preparation, using existing checkout/worktree/builder owners."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import platform
import sys

from benchmark_core.bootstrap import ProjectEnvironmentBuilder
from benchmark_core.cas import FileSystemCAS
from benchmark_core.checkout import SharedGitCache
from benchmark_core.manifest import load_json, project_from_mapping
from benchmark_core.worktree import WorktreeManager
from benchmark_core.execution import ProcessRunner, CommandSpec


def acquire(root: Path, entry, source_dir: Path, network: bool):
    bundle = source_dir / (entry.project_id + ".bundle")
    local = source_dir / entry.project_id
    transport = str(bundle.resolve()) if bundle.is_file() else str(local.resolve()) if (local / ".git").exists() else None
    if transport is None and not network:
        raise ValueError("OFFLINE_SOURCE_MISSING: use packaged seeds or projects --allow-network")
    snapshot = SharedGitCache(root / ".bench/git-cache").ensure(
        transport or entry.repository, entry.commit, expected_source_tree_digest=entry.source_digest)
    return replace(snapshot, repository=entry.repository)


def export_seed(snapshot, destination: Path) -> None:
    if destination.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    runner = ProcessRunner()
    prefix = ("git", "--git-dir", str(snapshot.bare_repository))
    for arguments in (("update-ref", "refs/heads/bench-seed", snapshot.commit),
                      ("bundle", "create", str(destination), "refs/heads/bench-seed")):
        result = runner.run(CommandSpec((*prefix, *arguments), 120))
        if not result.succeeded:
            destination.unlink(missing_ok=True)
            raise RuntimeError("SEED_EXPORT_FAILED")


def prepare_project(root: Path, entry, config, *, source_dir: Path, network: bool, build: bool) -> dict:
    if build and not network:
        raise ValueError("LOCAL_BUILD_NEEDS_EXPLICIT_NETWORK_PERMISSION_FOR_DEPENDENCIES")
    data = load_json(entry.manifest_path)
    project = project_from_mapping(data)
    snapshot = acquire(root, entry, source_dir, network)
    manager = WorktreeManager(root / ".bench/worktrees")
    with manager.disposable(snapshot) as worktree:
        manager.verify_pristine(worktree, expected_source_tree_digest=entry.source_digest)
        license_file = worktree.path / data["legal"]["license_file"]
        if not license_file.resolve().is_relative_to(worktree.path.resolve()):
            raise ValueError("LICENSE_PATH_ESCAPES_SOURCE")
        license_digest = "sha256:" + hashlib.sha256(license_file.read_bytes()).hexdigest()
        if license_digest != data["legal"]["license_file_digest"]:
            raise ValueError("LICENSE_DIGEST_MISMATCH")
        result = {"status": "SOURCE_VERIFIED", "project_id": entry.project_id,
                  "source_digest": entry.source_digest, "commit": entry.commit,
                  "authoritative": False, "baseline_run": False, "qualified_coding_tasks": 0}
        export_seed(snapshot, root / ".bench/seeds" / (entry.project_id + ".bundle"))
        if not build:
            return result
        python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if platform.system().lower() not in data["platforms"]["operating_systems"] or python not in data["platforms"]["python"]:
            raise ValueError("UNSUPPORTED_PROJECT_PLATFORM")
        install = replace(project.bootstrap.install, timeout_seconds=min(
            project.bootstrap.install.timeout_seconds, config.budgets.build_seconds))
        commands = tuple(replace(command, timeout_seconds=min(command.timeout_seconds, config.budgets.baseline_seconds))
                         for command in project.baseline.commands)
        project = replace(project, bootstrap=replace(project.bootstrap, install=install),
                          baseline=replace(project.baseline, commands=commands))
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        built = ProjectEnvironmentBuilder(root / ".bench/environments", FileSystemCAS(root / ".bench/cas")).build_and_verify(project, worktree.path)
        result.update(status="BASELINE_CHECKED" if built.admitted else "BASELINE_FAILED",
                      baseline_run=True, baseline_status=built.status.value,
                      evidence_refs=list(built.evidence_refs),
                      isolation="EXPLICIT_LOCAL_DIAGNOSTIC_NOT_OS_SANDBOXED")
        return result
