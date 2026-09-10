"""Secret-free zero-paid contract preflight for the ten locked SWE-bench bases.

This is an independent substrate oracle. It never imports ADCP and never invokes a
model or grader. It proves that the locked production scope policy selects only
bounded UTF-8 mode-100644 text from each exact public base tree, and that a real
Git index edit preserves every untouched tree entry mode/type/OID exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from suites.coding.phase3d_scope import MAX_SCOPE_BYTES, MAX_SCOPE_FILES, SCOPE_POLICY, select_write_scope
from tools.phase3d_adcp_compatibility_preflight import (
    TASK_REPOSITORY,
    TASK_REPOSITORY_COMMIT,
    TASKS,
    _ALLOWED_TASK_FILES,
    _FORBIDDEN_TASK_NAMES,
    changed_text,
    ensure_repository,
    git,
    prepare_worktree,
    read_public_task_file,
    remove_worktree,
    validate_task_metadata,
)


def tree_entries(repo: Path, revision: str) -> dict[str, tuple[str, str, str]]:
    output = git(repo, "ls-tree", "-rz", "-r", revision).stdout.decode("utf-8", "strict")
    result: dict[str, tuple[str, str, str]] = {}
    for row in output.split("\0"):
        if not row:
            continue
        metadata, path = row.split("\t", 1)
        mode, kind, oid = metadata.split()
        if path in result or path.casefold() in {name.casefold() for name in result}:
            raise ValueError("duplicate/case-colliding path in exact base tree")
        result[path] = (mode, kind, oid)
    if not result:
        raise ValueError("empty exact base tree")
    return result


def mode_counts(entries: dict[str, tuple[str, str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mode, kind, _oid in entries.values():
        key = f"{mode}:{kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def exercise_base(
    *,
    task_id: str,
    repository: str,
    base_commit: str,
    instruction: str,
    bare: Path,
    worktree: Path,
) -> dict[str, object]:
    prepare_worktree(bare, worktree, "base-contract-" + task_id, base_commit)
    try:
        scope = select_write_scope(str(worktree), instruction)
        if scope.policy != SCOPE_POLICY or scope.baseline_commit != base_commit:
            raise ValueError("scope selector drifted from locked base")
        if not 1 <= len(scope.paths) <= MAX_SCOPE_FILES:
            raise ValueError("scope file count is outside the locked bound")
        if not 0 < scope.visible_bytes <= MAX_SCOPE_BYTES:
            raise ValueError("scope byte count is outside the locked bound")

        exact_tree = git(worktree, "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
        baseline = tree_entries(worktree, base_commit)
        selected_bytes = 0
        selected_text: dict[str, str] = {}
        for path in scope.paths:
            identity = baseline.get(path)
            if identity is None or identity[0] != "100644" or identity[1] != "blob":
                raise ValueError(f"production scope selected non-editable Git entry: {path}")
            payload = git(worktree, "show", f"{base_commit}:{path}").stdout
            if b"\0" in payload:
                raise ValueError(f"production scope selected binary/NUL source: {path}")
            try:
                text = payload.decode("utf-8", "strict")
            except UnicodeDecodeError as error:
                raise ValueError(f"production scope selected non-UTF8 source: {path}") from error
            selected_bytes += len(payload)
            selected_text[path] = text
        if selected_bytes != scope.visible_bytes:
            raise ValueError(
                f"scope byte accounting mismatch: selector={scope.visible_bytes} exact={selected_bytes}"
            )
        if selected_bytes > MAX_SCOPE_BYTES:
            raise ValueError("selected model-visible source exceeds locked byte budget")

        edit_path = scope.paths[0]
        edited_text = changed_text(selected_text[edit_path], scope.visible_bytes)
        if edited_text == selected_text[edit_path]:
            raise ValueError("base-tree oracle mutation made no change")
        target = worktree.joinpath(*edit_path.split("/"))
        target.write_bytes(edited_text.encode("utf-8"))
        git(worktree, "add", "--", edit_path)
        candidate_tree = git(worktree, "write-tree").stdout.decode("ascii").strip()
        candidate = tree_entries(worktree, candidate_tree)

        if set(candidate) != set(baseline):
            raise ValueError("allowed text edit changed exact repository path set")
        for path, identity in baseline.items():
            if path == edit_path:
                continue
            if candidate[path] != identity:
                raise ValueError(f"untouched Git identity changed: {path}")
        if candidate[edit_path][0:2] != ("100644", "blob"):
            raise ValueError("allowed text edit changed regular-file mode/type")
        if candidate[edit_path][2] == baseline[edit_path][2]:
            raise ValueError("allowed text edit did not create a distinct Git blob")
        if git(worktree, "write-tree").stdout.decode("ascii").strip() != candidate_tree:
            raise ValueError("real git write-tree is not stable after allowed edit")

        opaque_count = sum(
            1
            for path, (mode, kind, _oid) in baseline.items()
            if path not in scope.paths or mode != "100644" or kind != "blob"
        )
        return {
            "task_id": task_id,
            "repository": repository,
            "base_commit": base_commit,
            "base_tree": exact_tree,
            "scope_policy": scope.policy,
            "scope_digest": scope.digest,
            "scope_paths": list(scope.paths),
            "scope_files": len(scope.paths),
            "scope_visible_bytes": scope.visible_bytes,
            "inventory_entries": len(baseline),
            "inventory_mode_counts": mode_counts(baseline),
            "opaque_or_out_of_scope_entries": opaque_count,
            "edited_path": edit_path,
            "candidate_tree": candidate_tree,
            "selected_source_utf8_only": True,
            "selected_source_nul_free": True,
            "selected_source_mode_100644_only": True,
            "untouched_entries_preserved": True,
            "real_write_tree_match": True,
            "status": "PASS",
        }
    finally:
        remove_worktree(bare, worktree)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=Path(".autobench-cache/phase3d-base-contract"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase3d/BASE_TREE_CONTRACT_PREFLIGHT.json"),
    )
    args = parser.parse_args()

    cache_root = args.cache_root.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    task_repo = ensure_repository(cache_root, TASK_REPOSITORY, TASK_REPOSITORY_COMMIT)

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="autobench-phase3d-base-contract-") as temp_name:
        temp_root = Path(temp_name)
        for index, (task_id, (repository, base_commit)) in enumerate(TASKS.items(), start=1):
            validate_task_metadata(task_repo, task_id, repository, base_commit)
            instruction = read_public_task_file(task_repo, task_id, "problem_statement.md")
            source_repo = ensure_repository(cache_root, repository, base_commit)
            result = exercise_base(
                task_id=task_id,
                repository=repository,
                base_commit=base_commit,
                instruction=instruction,
                bare=source_repo,
                worktree=temp_root / f"task-{index:02d}",
            )
            results.append(result)
            print(
                f"[{index:02d}/10] {task_id}: PASS "
                f"({result['scope_files']} files, {result['scope_visible_bytes']} bytes)"
            )

    if len(results) != 10 or {row["task_id"] for row in results} != set(TASKS):
        raise ValueError("base-tree contract preflight did not cover the exact locked corpus")
    evidence: dict[str, object] = {
        "schema_version": 1,
        "scope": "PHASE3D_LOCKED_BASE_TREE_CONTRACT_PREFLIGHT",
        "status": "PASS",
        "swebench_task_repository": TASK_REPOSITORY,
        "swebench_task_repository_commit": TASK_REPOSITORY_COMMIT,
        "task_count": 10,
        "tasks_passed": 10,
        "scope_policy": SCOPE_POLICY,
        "scope_max_files": MAX_SCOPE_FILES,
        "scope_max_visible_bytes": MAX_SCOPE_BYTES,
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
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"locked base-tree contract preflight: 10/10 PASS; evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
