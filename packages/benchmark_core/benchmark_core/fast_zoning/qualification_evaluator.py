"""Hash-bound protocol adapter for the frozen qualification-v1 evaluators.

The source evaluator functions are executed unchanged.  Only the five small
``fast_ab`` helpers they depend on are loaded, avoiding unrelated zoning imports.
This is a protocol adapter, not a second implementation of evaluator semantics.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any


CATEGORY_MAPPING = {
    "EXISTING_SUITE": ("existing_suite", "required_existing_suite"),
    "NARROW_ORACLE": ("targeted_oracle", "required_targeted_oracle"),
    "DIFFERENTIAL_CHECK": ("differential_check", "required_differential_checks"),
    "METAMORPHIC_CHECK": ("metamorphic_check", "required_metamorphic_checks"),
    "CROSS_COMPONENT_CHECK": ("cross_component_check", "required_cross_component_checks"),
}
SOURCE_MODULES = {
    "fast_ab.py": "3649e149a5301b2f48db279ef3bc277471f52ae92ab7629be5f69d16b50611b5",
    "fast_ab_results.py": "4a2edaf9bdb3c9f57d2aaee81127f8307d6f949ea9440649be2b394fe802b340",
    "fast_ab_evaluation.py": "0f74293185a0206c68a4de9d33cf14279153a42c117b56e80ee6b9f9aa4ed6ac",
    "oracle_runner.py": "d2423bbf4c4475105cc619abf94324e67b20127437be51a6fb48fdf6fc57fdde",
}
HELPERS = {"sha256", "write_json", "git", "verify_oracle", "evaluate"}


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def _strict_json(payload: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("CACHE_PLAN_DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("CACHE_PLAN_NONFINITE_JSON")
    value = json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("CACHE_PLAN_JSON_OBJECT_REQUIRED")
    return value


def _regular_path(path: Path) -> Path:
    """Reject traversal spellings and symlink/junction components before resolving."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("CACHE_PLAN_NONCANONICAL_PATH")
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("CACHE_PLAN_LINK_PATH")
    if not path.is_file():
        raise ValueError("CACHE_PLAN_REGULAR_FILE_REQUIRED")
    return path.resolve()


def load_bound_source_plan(path: Path, expected_sha256: str) -> dict:
    """Read only the independently bound origin, rejecting ambiguous JSON."""
    payload = _regular_path(path).read_bytes()
    if _hash(payload) != expected_sha256:
        raise ValueError("CACHE_PLAN_ORIGIN_HASH_MISMATCH")
    return _strict_json(payload)


def evaluator_layout(source_plan: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    """Pure translator layout: maps plus ordered (source path, name, digest)."""
    paths, inputs, identities = {}, [], set()
    rows = source_plan["evaluators"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("CACHE_PLAN_EMPTY_EVALUATORS")
    for index, row in enumerate(rows):
        identity = row["id"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("CACHE_PLAN_DUPLICATE_EVALUATOR")
        identities.add(identity)
        category = row["category"]
        if category not in CATEGORY_MAPPING:
            raise ValueError("Unsupported qualification evaluator category")
        if type(source_plan[CATEGORY_MAPPING[category][1]]) is not bool:
            raise ValueError("CACHE_PLAN_REQUIRED_FLAG_INVALID")
        runner = row["runner"]
        if runner not in ("pytest", "frozen_oracle", "differential"):
            raise ValueError("Unsupported executable evaluator")
        stems = {"pytest": (), "frozen_oracle": ("oracle",),
                 "differential": ("cases", "reference", "probe")}[runner]
        paths[identity] = {}
        for stem in stems:
            source = row[stem + "_path"]
            if not isinstance(source, str) or not source or not Path(source).name:
                raise ValueError("CACHE_PLAN_INPUT_PATH_INVALID")
            name = f"{index}-{stem}-{Path(source).name}"
            paths[identity][stem + "_path"] = name
            inputs.append((source, name, row[stem + "_sha256"]))
    return paths, inputs


def evaluator_rows(source_plan: dict, artifacts: list[dict], interpreter: str) -> list[dict]:
    """Pure campaign row construction shared by translation and validation."""
    evaluator_layout(source_plan)
    return [{"id": row["id"], "category": CATEGORY_MAPPING[row["category"]][0],
             "required": source_plan[CATEGORY_MAPPING[row["category"]][1]],
             "identity": "qualification-v1:" + row["id"],
             "command": [interpreter, "-I", "-B", "{artifact0}",
                         "--binding", "{artifact1}", "--workspace", "{workspace}",
                         "--evaluator", row["id"]],
             "timeout_seconds": 300, "artifacts": deepcopy(artifacts)}
            for row in source_plan["evaluators"]]


def verify_cache_plan_binding(source_plan_path: Path, source_plan_sha256: str,
                              rows: list[dict], *, interpreter: str,
                              native_module_paths: dict[str, str],
                              native_module_dir: Path) -> dict:
    """Verify prepared translation without writes, imports, spawning or evaluation.

    Native paths must be supplied from the actual imported modules by the caller.
    This verifies frozen inputs, not execution authority or evaluator outcomes.
    """
    source_plan = load_bound_source_plan(source_plan_path, source_plan_sha256)
    paths, inputs = evaluator_layout(source_plan)
    if not isinstance(rows, list) or not rows or len(rows[0].get("artifacts", [])) < 2:
        raise ValueError("CACHE_PLAN_ARTIFACTS_MISSING")
    binding_path = _regular_path(Path(rows[0]["artifacts"][1]["path"]))
    root = binding_path.parent
    if binding_path.name != "binding.json":
        raise ValueError("CACHE_PLAN_BINDING_NAME_INVALID")
    binding_payload = binding_path.read_bytes()
    binding = _strict_json(binding_payload)
    # JSON encoding comparison also distinguishes booleans from integers.
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if canonical(binding.get("source_plan")) != canonical(source_plan):
        raise ValueError("CACHE_PLAN_SOURCE_PLAN_MISMATCH")
    adapter = _regular_path(Path(__file__))
    expected_artifacts = [{"path": "qualification_evaluator.py", "sha256": _hash(adapter.read_bytes())}]
    expected_artifacts += [{"path": name, "sha256": digest} for name, digest in SOURCE_MODULES.items()]
    expected_artifacts += [{"path": name, "sha256": digest} for _, name, digest in inputs]
    expected_binding = {"source_plan": source_plan, "modules": {name: name for name in SOURCE_MODULES},
                        "paths": paths, "artifacts": expected_artifacts}
    if canonical(binding) != canonical(expected_binding):
        raise ValueError("CACHE_PLAN_LAYOUT_MISMATCH")
    file_identities = set()
    for artifact in expected_artifacts:
        target = _regular_path(root / artifact["path"])
        if target.parent != root or _hash(target.read_bytes()) != artifact["sha256"]:
            raise ValueError("CACHE_PLAN_ARTIFACT_HASH_MISMATCH")
        info = target.stat()
        identity = (info.st_dev, info.st_ino)
        if identity in file_identities:
            raise ValueError("CACHE_PLAN_ARTIFACT_ALIAS")
        file_identities.add(identity)
    # The original native plan consumes these paths; bind them too, not just copies.
    for source, _, digest in inputs:
        original = _regular_path(Path(source_plan_path).parent / source)
        if _hash(original.read_bytes()) != digest:
            raise ValueError("CACHE_PLAN_NATIVE_INPUT_HASH_MISMATCH")
    if set(native_module_paths) != set(SOURCE_MODULES):
        raise ValueError("CACHE_PLAN_NATIVE_MODULE_SET_MISMATCH")
    for name, digest in SOURCE_MODULES.items():
        assigned = _regular_path(Path(native_module_dir) / name)
        loaded = _regular_path(Path(native_module_paths[name]))
        if loaded != assigned or _hash(loaded.read_bytes()) != digest:
            raise ValueError("CACHE_PLAN_NATIVE_MODULE_MISMATCH")
    artifacts = [{"path": str(root / entry["path"]), "sha256": entry["sha256"]}
                 for entry in expected_artifacts]
    artifacts.insert(1, {"path": str(binding_path), "sha256": _hash(binding_payload)})
    expected_rows = evaluator_rows(source_plan, artifacts, interpreter)
    if canonical(rows) != canonical(expected_rows):
        raise ValueError("CACHE_PLAN_ROWS_MISMATCH")
    return source_plan


def translate_evaluators(source_plan: dict, source_plan_path: Path,
                         source_module_dir: Path, output_dir: Path) -> list[dict]:
    """Copy immutable evaluator dependencies and emit campaign-v1 protocol rows.

    Callers validate qualification evidence and the canonical source digest.
    This function independently validates every declared artifact hash. All
    transitive Python evaluator code is pinned in each emitted row as well.
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    artifacts: list[dict] = []

    def retain(path: Path, destination: Path, expected: str | None = None) -> Path:
        payload = path.read_bytes()
        digest = _hash(payload)
        if expected is not None and digest != expected:
            raise ValueError(f"Source evaluator artifact hash mismatch: {path}")
        destination.write_bytes(payload)
        artifacts.append({"path": str(destination), "sha256": digest})
        return destination

    retain(Path(__file__), output_dir / "qualification_evaluator.py")
    modules = {name: retain(Path(source_module_dir) / name, output_dir / name, digest).name
               for name, digest in SOURCE_MODULES.items()}
    paths, inputs = evaluator_layout(source_plan)
    for source, name, digest in inputs:
        retain((Path(source_plan_path).parent / source).resolve(), output_dir / name, digest)
    binding_path = output_dir / "binding.json"
    binding = {"source_plan": deepcopy(source_plan), "modules": modules,
               "paths": paths, "artifacts": [artifact | {"path": Path(artifact["path"]).name}
                                             for artifact in artifacts]}
    _write_json(binding_path, binding)
    # The campaign runner pins the adapter and binding before either is executed.
    complete_artifacts = [artifacts[0], {"path": str(binding_path),
                                       "sha256": _hash(binding_path.read_bytes())}, *artifacts[1:]]
    return evaluator_rows(source_plan, complete_artifacts, sys.executable)


def _load_source_functions(binding: dict) -> dict:
    """Load exact source bodies with only their original standard-library imports."""
    modules = binding["modules"]
    namespace: dict[str, Any] = {"__name__": "__qualification_bridge__",
                                "__file__": modules["fast_ab.py"]}
    fast_ab = ast.parse(Path(modules["fast_ab.py"]).read_bytes())
    names = [node.name for node in fast_ab.body if isinstance(node, ast.FunctionDef)
             and node.name in HELPERS]
    if len(names) != len(HELPERS) or set(names) != HELPERS:
        raise ValueError("Unsupported source evaluator helper definitions")
    selected = []
    for node in fast_ab.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module and (module.startswith("omp_zones") or module.startswith("repository_intelligence")):
                continue
            selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HELPERS:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("CLEAN_HEAD", "ORACLE_HASH") for t in node.targets):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), modules["fast_ab.py"], "exec"), namespace)
    exec(compile(Path(modules["fast_ab_results.py"]).read_bytes(), modules["fast_ab_results.py"], "exec"), namespace)
    evaluator = ast.parse(Path(modules["fast_ab_evaluation.py"]).read_bytes())
    evaluator.body = [node for node in evaluator.body if not (
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("omp_zones."))]
    exec(compile(evaluator, modules["fast_ab_evaluation.py"], "exec"), namespace)
    return namespace


def evaluate_binding(binding_path: Path, workspace: Path, evaluator_id: str) -> dict:
    """Return exactly one source evaluator result in campaign's JSON protocol."""
    binding = json.loads(Path(binding_path).read_bytes())
    root = Path(binding_path).resolve().parent
    def bound_path(value: str) -> str:
        path = (root / value).resolve()
        if path.parent != root:
            raise ValueError("Qualification dependency escapes bound directory")
        return str(path)
    for artifact in binding["artifacts"]:
        if _hash(Path(bound_path(artifact["path"])).read_bytes()) != artifact["sha256"]:
            raise ValueError(f"Frozen qualification dependency changed: {artifact['path']}")
    binding["modules"] = {name: bound_path(path) for name, path in binding["modules"].items()}
    binding["paths"] = {name: {key: bound_path(path) for key, path in paths.items()}
                        for name, paths in binding["paths"].items()}
    plan = deepcopy(binding["source_plan"])
    selected = [row for row in plan["evaluators"] if row["id"] == evaluator_id]
    if len(selected) != 1:
        raise ValueError("Evaluator identity is not uniquely declared")
    selected[0].update(binding["paths"][evaluator_id])
    plan["evaluators"] = selected
    # Source runner validates category presence. A per-row invocation contains
    # only that category; requirement flags do not control evaluator execution.
    for category, (_, requirement) in CATEGORY_MAPPING.items():
        plan[requirement] = bool(binding["source_plan"][requirement] and selected[0]["category"] == category)
    namespace = _load_source_functions(binding)
    workspace = Path(workspace).resolve()
    # Keep logs beside this arm's disposable evaluator clone, never in candidate
    # source. Source result paths remain usable for later morning inspection.
    directory = Path(tempfile.mkdtemp(prefix="qualification-evaluator-", dir=workspace.parent))
    result = namespace["run_evaluators"](plan, workspace, directory)
    return result["evaluators"][evaluator_id] | {"source_evidence_directory": str(directory)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evaluator", required=True)
    arguments = parser.parse_args()
    try:
        result = evaluate_binding(arguments.binding, arguments.workspace, arguments.evaluator)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        result = {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
