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
    paths: dict[str, dict[str, str]] = {}
    for index, row in enumerate(source_plan["evaluators"]):
        if row["category"] not in CATEGORY_MAPPING:
            raise ValueError(f"Unsupported qualification evaluator category: {row['category']}")
        if row["runner"] not in ("pytest", "frozen_oracle", "differential"):
            raise ValueError(f"Unsupported executable evaluator: {row['runner']}")
        stems = {"pytest": (), "frozen_oracle": ("oracle",),
                 "differential": ("cases", "reference", "probe")}[row["runner"]]
        paths[row["id"]] = {}
        for stem in stems:
            source = (Path(source_plan_path).parent / row[stem + "_path"]).resolve()
            target = output_dir / f"{index}-{stem}-{source.name}"
            paths[row["id"]][stem + "_path"] = retain(source, target, row[stem + "_sha256"]).name
    binding_path = output_dir / "binding.json"
    binding = {"source_plan": deepcopy(source_plan), "modules": modules,
               "paths": paths, "artifacts": [artifact | {"path": Path(artifact["path"]).name}
                                             for artifact in artifacts]}
    _write_json(binding_path, binding)
    # The campaign runner pins the adapter and binding before either is executed.
    complete_artifacts = [artifacts[0], {"path": str(binding_path),
                                       "sha256": _hash(binding_path.read_bytes())}, *artifacts[1:]]
    return [{"id": row["id"], "category": CATEGORY_MAPPING[row["category"]][0],
             "required": source_plan[CATEGORY_MAPPING[row["category"]][1]],
             "identity": "qualification-v1:" + row["id"],
             "command": [sys.executable, "-I", "-B", "{artifact0}",
                         "--binding", "{artifact1}", "--workspace", "{workspace}",
                         "--evaluator", row["id"]],
             "timeout_seconds": 300, "artifacts": deepcopy(complete_artifacts)}
            for row in source_plan["evaluators"]]


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
