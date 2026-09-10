"""Zero-paid compatibility preflight for the locked Phase 3D ADCP treatment.

This tool never invokes a model or an official SWE-bench grader. It reads only
public task input metadata (task.yaml + problem_statement.md), checks out each
locked source repository at its exact base commit, and exercises the pinned ADCP
Git substrate on a disposable branch. Hidden grader material is never opened or
passed to ADCP.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from suites.coding.phase3d_scope import MAX_SCOPE_BYTES, SCOPE_POLICY, select_write_scope


TASK_REPOSITORY = "SWE-bench/swe-bench-tasks"
TASK_REPOSITORY_COMMIT = "3d07b464b7b311a0cbfb5ed5b2d8a3b96f84a33d"
TASKS = {
    "astropy__astropy-12907": ("astropy/astropy", "d16bfe05a744909de4b27f5875fe0d4ed41ce607"),
    "django__django-10880": ("django/django", "838e432e3e5519c5383d12018e6c78f8ec7833c1"),
    "matplotlib__matplotlib-13989": ("matplotlib/matplotlib", "a3e2897bfaf9eaac1d6649da535c4e721c89fa69"),
    "pallets__flask-5014": ("pallets/flask", "7ee9ceb71e868944a46e1ff00b506772a53a4f1d"),
    "psf__requests-1142": ("psf/requests", "22623bd8c265b78b161542663ee980738441c307"),
    "pydata__xarray-2905": ("pydata/xarray", "7c4e2ac83f7b4306296ff9b7b51aaf016e5ad614"),
    "pylint-dev__pylint-6528": ("pylint-dev/pylint", "273a8b25620467c1e5686aa8d2a1dbb8c02c78d0"),
    "pytest-dev__pytest-10081": ("pytest-dev/pytest", "da9a2b584eb7a6c7e924b2621ed0ddaeca0a7bea"),
    "scikit-learn__scikit-learn-10297": ("scikit-learn/scikit-learn", "b90661d6a46aa3619d3eec94d5281f5888add501"),
    "sympy__sympy-20590": ("sympy/sympy", "cffd4e0f86fefd4802349a9f9b19ed70934ea354"),
}
_ALLOWED_TASK_FILES = frozenset(("task.yaml", "problem_statement.md"))
_FORBIDDEN_TASK_NAMES = frozenset((
    "gold.patch", "test.patch", "tests.json", "FAIL_TO_PASS", "PASS_TO_PASS",
))
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class GitResult:
    stdout: bytes
    stderr: bytes


def git(path: Path, *args: str, input_bytes: bytes | None = None, check: bool = True) -> GitResult:
    env = {key: value for key, value in __import__("os").environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        env=env,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-4000:])
    return GitResult(result.stdout, result.stderr)


def require_exact_head(path: Path, expected: str, label: str) -> None:
    actual = git(path, "rev-parse", "HEAD").stdout.decode("ascii").strip().lower()
    if actual != expected:
        raise ValueError(f"{label} commit mismatch: expected {expected}, got {actual}")


def ensure_repository(cache_root: Path, repository: str, commit: str) -> Path:
    slug = repository.replace("/", "__")
    bare = cache_root / "git" / (slug + ".git")
    bare.parent.mkdir(parents=True, exist_ok=True)
    if not bare.exists():
        result = subprocess.run(
            ["git", "clone", "--bare", "--filter=blob:none", f"https://github.com/{repository}.git", str(bare)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace")[-4000:])
    fetch = subprocess.run(
        ["git", "-C", str(bare), "fetch", "--no-tags", "origin", commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    if fetch.returncode:
        raise RuntimeError(fetch.stderr.decode("utf-8", "replace")[-4000:])
    actual = git(bare, "rev-parse", commit + "^{commit}").stdout.decode("ascii").strip().lower()
    if actual != commit:
        raise ValueError(f"cannot bind {repository} to exact commit {commit}")
    return bare


def read_public_task_file(task_repo: Path, task_id: str, name: str) -> str:
    if name not in _ALLOWED_TASK_FILES or name in _FORBIDDEN_TASK_NAMES:
        raise ValueError("preflight attempted to access non-public-evaluation input")
    path = f"tasks/{task_id}/{name}"
    return git(task_repo, "show", f"{TASK_REPOSITORY_COMMIT}:{path}").stdout.decode("utf-8", "strict")


def validate_task_metadata(task_repo: Path, task_id: str, repository: str, base_commit: str) -> None:
    metadata = read_public_task_file(task_repo, task_id, "task.yaml")
    repo_match = re.search(r"(?m)^repo:\s*([^\s]+)\s*$", metadata)
    base_match = re.search(r"(?m)^base_commit:\s*([0-9a-f]{40})\s*$", metadata)
    instance_match = re.search(r"(?m)^instance_id:\s*([^\s]+)\s*$", metadata)
    if (
        repo_match is None
        or base_match is None
        or instance_match is None
        or repo_match.group(1) != repository
        or base_match.group(1) != base_commit
        or instance_match.group(1) != task_id
    ):
        raise ValueError(f"locked public task metadata drift for {task_id}")


def configure_adcp_imports(adcp_root: Path, expected_sha: str):
    require_exact_head(adcp_root, expected_sha, "ADCP")
    shared = adcp_root / "packages" / "shared_contracts" / "src"
    if not (shared / "shared_contracts" / "__init__.py").is_file():
        raise ValueError("ADCP shared_contracts source is missing")
    sys.path.insert(0, str(adcp_root))
    sys.path.insert(0, str(shared))

    import shared_contracts as sc
    from packages.zone_development.contracts import FileEdit
    from packages.zone_development.workspace import GitWorkspace

    return sc, FileEdit, GitWorkspace


def prepare_worktree(bare: Path, destination: Path, task_id: str, base_commit: str) -> None:
    branch = "autobench-preflight-" + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:20]
    subprocess.run(
        ["git", "-C", str(bare), "branch", "-D", branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result = subprocess.run(
        ["git", "-C", str(bare), "worktree", "add", "-f", "-b", branch, str(destination), base_commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-4000:])
    require_exact_head(destination, base_commit, task_id)


def remove_worktree(bare: Path, destination: Path) -> None:
    subprocess.run(
        ["git", "-C", str(bare), "worktree", "remove", "--force", str(destination)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )


def entry_identity(entry) -> tuple[str, str, str, int | None]:
    return entry.mode, entry.kind, entry.oid, entry.size


def changed_text(original_text: str, visible_bytes: int) -> str:
    if original_text.endswith("\n"):
        return original_text[:-1]
    if visible_bytes < MAX_SCOPE_BYTES:
        return original_text + "\n"
    if not original_text:
        raise ValueError("cannot create a bounded non-empty text mutation at the exact source limit")
    replacement = " " if original_text[-1] != " " else "\t"
    return original_text[:-1] + replacement


def exercise_task(
    *,
    task_id: str,
    repository: str,
    base_commit: str,
    instruction: str,
    bare: Path,
    worktree: Path,
    sc,
    FileEdit,
    GitWorkspace,
) -> dict[str, object]:
    prepare_worktree(bare, worktree, task_id, base_commit)
    try:
        scope = select_write_scope(str(worktree), instruction)
        if scope.policy != SCOPE_POLICY or scope.baseline_commit != base_commit:
            raise ValueError("scope selector is not bound to the exact base commit")
        workspace = GitWorkspace(worktree)
        repository_id = sc.RepositoryId(value="preflight-" + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24])
        baseline_ref = workspace.source_ref(repository_id)
        exact_tree = git(worktree, "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
        inventory = workspace.inventory()
        if inventory.tree_oid != exact_tree or inventory.git_tree() != exact_tree:
            raise ValueError("ADCP exact inventory does not reproduce the real base tree")

        by_path = inventory.by_path()
        for path in scope.paths:
            entry = by_path.get(path)
            if entry is None or entry.mode != "100644" or entry.kind != "blob":
                raise ValueError("static write scope contains a non-editable Git entry")

        projection = workspace.snapshot(max_bytes=MAX_SCOPE_BYTES, paths=scope.paths)
        if projection.tree_oid != exact_tree or projection.exact_inventory != inventory:
            raise ValueError("editable projection lost exact tree binding")
        projected_paths = set(projection.editable_paths())
        if not set(scope.paths).issubset(projected_paths):
            raise ValueError("write scope is not fully represented by editable UTF-8 source")
        wire = projection.to_wire()
        wire_paths = {path for path, _text in wire["files"]}
        opaque_paths = set(by_path) - projected_paths
        if wire_paths & opaque_paths:
            raise ValueError("opaque Git entry leaked into model projection")

        edit_path = scope.paths[0]
        original_text = dict(projection.files)[edit_path]
        edited_text = changed_text(original_text, scope.visible_bytes)
        if edited_text == original_text:
            raise ValueError("preflight text mutation must change the Git blob")
        request = SimpleNamespace(
            baseline=baseline_ref,
            write_scope=SimpleNamespace(paths=scope.paths),
            limits=SimpleNamespace(max_source_bytes=MAX_SCOPE_BYTES, max_patch_bytes=262144),
            session_id="preflight-" + hashlib.sha256((task_id + base_commit).encode("utf-8")).hexdigest()[:24],
        )
        proposal = SimpleNamespace(
            source=baseline_ref,
            edits=(FileEdit(path=edit_path, content=edited_text),),
        )
        before = {path: entry_identity(entry) for path, entry in by_path.items()}
        result_ref = workspace.apply(request, proposal, sequence=1)
        after_inventory = workspace.inventory()
        after = after_inventory.by_path()
        for path, identity in before.items():
            if path == edit_path:
                continue
            entry = after.get(path)
            if entry is None or entry_identity(entry) != identity:
                raise ValueError(f"untouched Git identity changed: {path}")
        if after[edit_path].mode != "100644" or after[edit_path].kind != "blob":
            raise ValueError("ordinary text edit changed Git mode/type")
        if after[edit_path].oid == by_path[edit_path].oid:
            raise ValueError("preflight edit did not produce a new text blob")
        write_tree = git(worktree, "write-tree").stdout.decode("ascii").strip()
        committed_tree = git(worktree, "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
        if write_tree != committed_tree or result_ref.tree.value != committed_tree:
            raise ValueError("post-edit tree does not equal real git write-tree")

        mode_counts: dict[str, int] = {}
        for entry in inventory.entries:
            key = f"{entry.mode}:{entry.kind}"
            mode_counts[key] = mode_counts.get(key, 0) + 1
        return {
            "task_id": task_id,
            "repository": repository,
            "base_commit": base_commit,
            "base_tree": exact_tree,
            "scope_policy": scope.policy,
            "scope_digest": scope.digest,
            "scope_paths": list(scope.paths),
            "scope_visible_bytes": scope.visible_bytes,
            "inventory_entries": len(inventory.entries),
            "inventory_mode_counts": dict(sorted(mode_counts.items())),
            "projection_files": len(projection.files),
            "projection_complete_text_tree": projection.complete_text_tree,
            "edited_path": edit_path,
            "candidate_tree": committed_tree,
            "untouched_entries_preserved": True,
            "real_write_tree_match": True,
            "status": "PASS",
        }
    finally:
        remove_worktree(bare, worktree)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adcp-root", type=Path, required=True)
    parser.add_argument("--adcp-sha", required=True)
    parser.add_argument("--cache-root", type=Path, default=Path(".autobench-cache/phase3d-compat"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/phase3d/ADCP_COMPATIBILITY_PREFLIGHT.json"))
    args = parser.parse_args()

    if _SHA1.fullmatch(args.adcp_sha) is None:
        raise SystemExit("--adcp-sha must be an exact lowercase SHA-1")
    adcp_root = args.adcp_root.resolve()
    sc, FileEdit, GitWorkspace = configure_adcp_imports(adcp_root, args.adcp_sha)

    cache_root = args.cache_root.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    task_repo = ensure_repository(cache_root, TASK_REPOSITORY, TASK_REPOSITORY_COMMIT)

    results = []
    with tempfile.TemporaryDirectory(prefix="autobench-phase3d-compat-") as temp_name:
        temp_root = Path(temp_name)
        for index, (task_id, expected) in enumerate(TASKS.items(), start=1):
            repository, base_commit = expected
            validate_task_metadata(task_repo, task_id, repository, base_commit)
            instruction = read_public_task_file(task_repo, task_id, "problem_statement.md")
            source_repo = ensure_repository(cache_root, repository, base_commit)
            result = exercise_task(
                task_id=task_id,
                repository=repository,
                base_commit=base_commit,
                instruction=instruction,
                bare=source_repo,
                worktree=temp_root / f"task-{index:02d}",
                sc=sc,
                FileEdit=FileEdit,
                GitWorkspace=GitWorkspace,
            )
            results.append(result)
            print(f"[{index:02d}/10] {task_id}: PASS")

    if len(results) != 10 or {item["task_id"] for item in results} != set(TASKS):
        raise ValueError("preflight did not cover the exact locked ten-task corpus")
    evidence = {
        "schema_version": 1,
        "scope": "PHASE3D_ADCP_ZERO_PAID_COMPATIBILITY_PREFLIGHT",
        "status": "PASS",
        "adcp_commit": args.adcp_sha,
        "swebench_task_repository": TASK_REPOSITORY,
        "swebench_task_repository_commit": TASK_REPOSITORY_COMMIT,
        "task_count": 10,
        "tasks_passed": 10,
        "scope_policy": SCOPE_POLICY,
        "model_called": False,
        "paid_model_called": False,
        "official_grader_called": False,
        "hidden_evaluation_material_used": False,
        "task_input_files_read": sorted(_ALLOWED_TASK_FILES),
        "forbidden_task_material": sorted(_FORBIDDEN_TASK_NAMES),
        "results": results,
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    evidence["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ADCP compatibility preflight: 10/10 PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
