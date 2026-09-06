"""Subprocess worker for the benchmark-owned Auto-Zoning v0.6 adapter."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping


def main() -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        request = json.load(sys.stdin)
        if not isinstance(request, Mapping):
            raise ValueError("worker request must be an object")
        invocation = request.get("invocation", {})
        source_snapshot = invocation.get("source_snapshot", {})
        if not isinstance(source_snapshot, Mapping) or "scope_paths" not in source_snapshot:
            raise ValueError("invocation.source_snapshot.scope_paths is required")
        scope_paths = source_snapshot["scope_paths"]
        if not isinstance(scope_paths, list) or any(not isinstance(path, str) for path in scope_paths):
            raise ValueError("invocation.source_snapshot.scope_paths must be a string list")
        analysis_scope = request.get("analysis_scope")
        if request.get("schema") == "autonomous-dev-bench/auto-zoning-worker-request/v2":
            if set(request) != {"schema", "repository", "runner_input_fingerprint", "analysis_scope", "invocation"}:
                raise ValueError("v2 worker request contains missing or unknown fields")
            if not isinstance(analysis_scope, Mapping) or set(analysis_scope) != {"mode", "paths"}:
                raise ValueError("analysis_scope must contain exactly mode and paths")
            mode, paths = analysis_scope.get("mode"), analysis_scope.get("paths")
            if mode not in {"FULL", "PATHS"} or not isinstance(paths, list):
                raise ValueError("analysis_scope requires FULL or PATHS and a paths list")
            if mode == "FULL" and paths:
                raise ValueError("FULL analysis requires an empty paths list")
            if mode == "PATHS" and not paths:
                raise ValueError("PATHS analysis requires at least one path")
            if paths != scope_paths:
                raise ValueError("analysis_scope paths must match source snapshot scope_paths")
            if source_snapshot.get("input_fingerprint") != request.get("runner_input_fingerprint"):
                raise ValueError("worker fingerprints do not match")
            normalized: list[str] = []
            for value in paths:
                if not isinstance(value, str) or not value:
                    raise ValueError("analysis paths must be non-empty strings")
                path = Path(value)
                parts = value.replace("\\", "/").split("/")
                if path.is_absolute() or value.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                    raise ValueError("analysis paths must be safe repository-relative paths")
                normalized.append(path.as_posix())
            if len(set(normalized)) != len(normalized):
                raise ValueError("analysis paths must be unique")
            seeds = None if mode == "FULL" else normalized
        else:
            seeds = [str(path) for path in scope_paths]
        declared_fingerprint = source_snapshot.get("input_fingerprint")
        runner_fingerprint = request.get("runner_input_fingerprint")
        import autozoning
        production_version = getattr(autozoning, "__version__", None)
        if production_version != "0.6.0":
            raise RuntimeError(f"expected Auto-Zoning 0.6.0, got {production_version!r}")
        from autozoning.semantic import RepositorySemanticFrontend
        from autozoning.semantic.projection import build_projection

        analysis = RepositorySemanticFrontend().analyze(
            Path(request["repository"]), seeds=seeds
        )
        projection = build_projection(analysis)
        combined = dict(projection)
        for name, default in (
            ("responsibility_to_zone", {}), ("facts", ()), ("files", ()),
            ("coverage", {}), ("process_status", None), ("semantic_completeness", "PARTIAL"),
        ):
            combined[name] = analysis.get(name, combined.get(name, default))
        combined.setdefault("status", analysis.get("status"))
        combined["semantic_status"] = analysis.get("status")
        combined["production_version"] = production_version
        combined["raw_analysis"] = analysis
        combined["raw_projection"] = projection
        combined["source_snapshot"] = source_snapshot
        combined["runner_input_fingerprint"] = runner_fingerprint
        combined["declared_input_fingerprint"] = declared_fingerprint
        combined["snapshot_binding_valid"] = (
            declared_fingerprint is not None and runner_fingerprint is not None
            and str(declared_fingerprint) == str(runner_fingerprint)
        )
        combined["user_request_recorded"] = bool(invocation.get("user_request"))
        json.dump(combined, sys.stdout, ensure_ascii=False, default=str)
        return 0
    except Exception as exc:
        json.dump({"status": "WORKER_FAILED", "error": f"{type(exc).__name__}: {exc}"}, sys.stdout)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
