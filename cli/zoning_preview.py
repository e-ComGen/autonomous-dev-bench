"""Advisory, reproducible Auto-Zoning previews for pinned real projects."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from benchmark_core.assets import asset_path
from benchmark_core.checkout import SharedGitCache, source_tree_digest
from benchmark_core.execution import ProcessRunner
from benchmark_core.identity import Sha256Digest, canonical_json
from benchmark_core.isolation import IsolationPolicy
from benchmark_core.manifest import load_project
from benchmark_core.result import RunStatus
from benchmark_core.worktree import WorktreeManager
from suites.auto_zoning.adapters import ProductionSemanticSubprocessAdapter

SCHEMA = "autonomous-dev-bench/zoning-preview/v1"
PROJECTS = {
    "httpx": "httpx.pinned_001", "httpx.pinned_001": "httpx.pinned_001",
    "requests": "requests.pinned_001", "requests.pinned_001": "requests.pinned_001",
    "pluggy": "pluggy.pinned_001", "pluggy.pinned_001": "pluggy.pinned_001",
}


@dataclass(frozen=True)
class PreviewRunContext:
    workspace: Path
    input_fingerprint: str


def _plain(value: object) -> Any:
    return json.loads(canonical_json(value))


def _semantic_canonical(value: Any) -> Any:
    """Canonicalize semantic collections whose ordering carries no meaning."""
    if isinstance(value, Mapping):
        return {str(key): _semantic_canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        normalized = [_semantic_canonical(item) for item in value]
        return sorted(normalized, key=canonical_json)
    return value


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _sorted_records(value: object, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    records = [_semantic_canonical(item) for item in _records(_plain(value))]
    return sorted(records, key=lambda item: tuple(str(item.get(key, "")) for key in keys))


def proposal_from_observation(observation: object) -> dict[str, Any]:
    attributes = getattr(observation, "attributes", {})
    raw = _plain(attributes.get("raw_output", {}))
    analysis = raw.get("raw_analysis", {}) if isinstance(raw.get("raw_analysis"), dict) else {}
    projection = raw.get("raw_projection", {}) if isinstance(raw.get("raw_projection"), dict) else {}
    coverage = analysis.get("coverage", raw.get("coverage", {}))
    zones = projection.get("zones", raw.get("zones", []))
    files = analysis.get("files", raw.get("files", []))
    return {
        "semantic_completeness": str(raw.get("semantic_completeness", analysis.get("semantic_completeness", "UNKNOWN"))),
        "mass": {
            "proposal": float(attributes.get("proposal_mass", 0.0)),
            "partial": float(attributes.get("partial_mass", 0.0)),
            "unknown": float(attributes.get("unknown_mass", 1.0)),
        },
        "coverage": _semantic_canonical(_plain(coverage)),
        "uncertainty": {
            "budget_exhausted": sorted(str(item) for item in analysis.get("budget_exhausted", [])),
            "missing_obligations": _semantic_canonical(_plain(analysis.get("missing_obligations", []))),
            "parse_errors": _semantic_canonical(_plain(analysis.get("parse_errors", []))),
        },
        "ownership": _sorted_records(attributes.get("ownership_proposal", []), ("responsibility_id", "zone_id")),
        "boundaries": _sorted_records(attributes.get("boundary_proposal", []), ("source_zone", "target_zone")),
        "zones": _sorted_records(zones, ("zone_id", "id")),
        "files": _sorted_records(files, ("path",)),
    }


def _semantic_agreement(reference: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[float, float, float]:
    def assignments(proposal: Mapping[str, Any]) -> dict[str, str]:
        return {str(item["responsibility_id"]): str(item["zone_id"]) for item in proposal.get("ownership", [])}
    def pairs(mapping: Mapping[str, str]) -> set[tuple[str, str]]:
        names = sorted(mapping)
        return {(left, right) for index, left in enumerate(names) for right in names[index + 1:]
                if mapping[left] == mapping[right]}
    def jaccard(left: set[object], right: set[object]) -> float:
        return 1.0 if not left and not right else len(left & right) / len(left | right)
    left, right = assignments(reference), assignments(candidate)
    common = set(left) & set(right)
    retention = 1.0 if not common else sum(left[item] == right[item] for item in common) / len(common)
    def semantic_boundaries(proposal: Mapping[str, Any], mapping: Mapping[str, str]) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
        members: dict[str, list[str]] = {}
        for responsibility, zone in mapping.items(): members.setdefault(zone, []).append(responsibility)
        return {(tuple(sorted(members.get(str(item["source_zone"]), []))),
                 tuple(sorted(members.get(str(item["target_zone"]), [])))) for item in proposal.get("boundaries", [])}
    return retention, jaccard(set(pairs(left)), set(pairs(right))), jaccard(
        set(semantic_boundaries(reference, left)), set(semantic_boundaries(candidate, right)))


def build_report(*, project: object, scope_mode: str, scope_paths: Sequence[str], run_records: Sequence[Mapping[str, Any]],
                 proposals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not run_records or len(run_records) != len(proposals):
        raise ValueError("preview requires one proposal for every run")
    public_runs = [{key: value for key, value in item.items() if key != "raw_output"} for item in run_records]
    analysis_digests = [str(item.get("analysis_digest", "")) for item in public_runs]
    proposal_digests = [str(Sha256Digest.of(item)) for item in proposals]
    all_passed = all(item.get("status") == RunStatus.PASS.value for item in public_runs)
    stable = (all_passed and all(analysis_digests)
              and all(bool(item.get("source_consistent")) and bool(item.get("snapshot_binding_valid"))
                      and bool(item.get("source_unchanged")) for item in public_runs)
              and len(set(analysis_digests)) == 1 and len(set(proposal_digests)) == 1)
    status = "PASS" if stable else ("FAIL" if all_passed else "INFRA_FAILURE")
    agreements = [_semantic_agreement(proposals[0], item) for item in proposals[1:]]
    minimum_agreement = tuple(min(item[index] for item in agreements) if agreements else 1.0 for index in range(3))
    source = getattr(project, "source")
    return {
        "schema": SCHEMA, "status": status, "advisory": True, "authority": "NONE",
        "project": {
            "project_id": getattr(project, "project_id"), "project_spec_digest": str(getattr(project, "content_digest")),
            "repository": str(source.repository), "commit_sha": str(source.commit_sha),
            "source_tree_digest": str(source.source_tree_digest),
        },
        "producer": {"system_id": "auto-zoning", "system_version": "0.6.0",
                     "adapter_id": "auto_zoning.production_api.v3", "adapter_version": "5"},
        "scope": {"mode": scope_mode, "paths": list(scope_paths)},
        "runs": {"requested": len(public_runs), "completed": len(public_runs), "items": public_runs},
        "stability": {
            "status": "STABLE" if stable else "UNSTABLE", "stable": stable,
            "analysis_digests": analysis_digests, "proposal_digests": proposal_digests,
            "distinct_analysis_digests": len(set(analysis_digests)),
            "distinct_proposal_digests": len(set(proposal_digests)),
            "minimum_exact_assignment_retention": minimum_agreement[0],
            "minimum_cozoning_pair_jaccard": minimum_agreement[1],
            "minimum_semantic_boundary_jaccard": minimum_agreement[2],
            "comparison": "analysis_digest + canonical proposal/v1; telemetry and generated_at excluded",
        },
        "proposal": proposals[0] if stable else None,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    project, stability = report["project"], report["stability"]
    lines = [f"# Auto-Zoning preview: {project['project_id']}", "",
             "> **Advisory only. Authority: NONE. This is not an architectural certification.**", "",
             f"- Commit: `{project['commit_sha']}`", f"- Source tree: `{project['source_tree_digest']}`",
             f"- Scope: `{report['scope']['mode']}`", f"- Stability: **{stability['status']}**",
             f"- Analysis digests: {stability['distinct_analysis_digests']}",
             f"- Proposal digests: {stability['distinct_proposal_digests']}",
             f"- Exact assignment retention: {stability['minimum_exact_assignment_retention']:.6f}",
             f"- Co-zoning pair Jaccard: {stability['minimum_cozoning_pair_jaccard']:.6f}",
             f"- Semantic boundary Jaccard: {stability['minimum_semantic_boundary_jaccard']:.6f}", ""]
    proposal = report.get("proposal")
    if not isinstance(proposal, Mapping):
        lines.extend(["No stable proposal is published; inspect the per-run records in JSON.", ""])
        return "\n".join(lines)
    mass = proposal["mass"]
    uncertainty = proposal["uncertainty"]
    lines.extend(["## Coverage and uncertainty", "", "| Metric | Value |", "|---|---:|",
                  f"| Proposal mass | {mass['proposal']:.6f} |", f"| Partial mass | {mass['partial']:.6f} |",
                  f"| Unknown mass | {mass['unknown']:.6f} |",
                  f"| Budget exhaustion reasons | {len(uncertainty['budget_exhausted'])} |",
                  f"| Missing obligations | {len(uncertainty['missing_obligations'])} |",
                  f"| Parse errors | {len(uncertainty['parse_errors'])} |", "", "## Proposed zones", "",
                  "| Zone | Display name | Responsibilities | Artifacts |", "|---|---|---:|---|"])
    for item in proposal["zones"]:
        artifacts = ", ".join(f"`{path}`" for path in item.get("artifact_paths", []))
        lines.append(f"| `{item.get('zone_id', '')}` | {item.get('display_name', '')} | {len(item.get('responsibility_ids', []))} | {artifacts} |")
    lines.extend(["", "## Ownership", "",
                  "| Responsibility | Zone | Mass |", "|---|---|---:|"])
    for item in proposal["ownership"]:
        lines.append(f"| `{item.get('responsibility_id', '')}` | `{item.get('zone_id', '')}` | {item.get('mass', '')} |")
    lines.extend(["", "## Boundaries", "", "| Source | Target | Mass |", "|---|---|---:|"])
    for item in proposal["boundaries"]:
        lines.append(f"| `{item.get('source_zone', '')}` | `{item.get('target_zone', '')}` | {item.get('mass', '')} |")
    lines.extend(["", "## Runs", "", "| Run | Status | Analysis digest | Proposal digest |", "|---:|---|---|---|"])
    for index, item in enumerate(report["runs"]["items"], 1):
        lines.append(f"| {index} | {item.get('status')} | `{item.get('analysis_digest', '')}` | `{stability['proposal_digests'][index-1]}` |")
    lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def run_project_preview(project_name: str, *, production_source: Path, python_executable: Path, cache_root: Path,
                        output_dir: Path, runs: int = 3, scope_paths: Sequence[str] = (), timeout: float = 180.0) -> dict[str, Any]:
    project_id = PROJECTS.get(project_name)
    if project_id is None:
        raise ValueError(f"unknown packaged project: {project_name}")
    if runs < 2:
        raise ValueError("runs must be at least 2 to measure stability")
    if not (production_source / "autozoning" / "semantic").is_dir():
        raise ValueError("production source must contain autozoning/semantic")
    project = load_project(asset_path(f"corpus/projects/{project_id}.json"))
    snapshot = SharedGitCache(cache_root / "git").ensure(
        str(project.source.repository), str(project.source.commit_sha),
        expected_source_tree_digest=str(project.source.source_tree_digest),
    )
    manager = WorktreeManager(cache_root / "worktrees")
    mode = "PATHS" if scope_paths else "FULL"
    benchmark_root = Path(__file__).resolve().parents[1]
    env_parts = [str(production_source.resolve()), str(benchmark_root), str(benchmark_root / "packages" / "benchmark_core")]
    if os.environ.get("PYTHONPATH"):
        env_parts.extend(str(Path(item).resolve()) for item in os.environ["PYTHONPATH"].split(os.pathsep) if item)
    env_path = os.pathsep.join(dict.fromkeys(env_parts))
    adapter = ProductionSemanticSubprocessAdapter(command=(str(python_executable), "-m", "suites.auto_zoning.worker"),
                                                   timeout_seconds=timeout,
                                                   environment={"PYTHONPATH": env_path, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"})
    run_records: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    with manager.disposable(snapshot) as item:
        manager.verify_pristine(item, expected_source_tree_digest=str(project.source.source_tree_digest))
        for index in range(1, runs + 1):
            before = source_tree_digest(item.path)
            command = adapter.prepare_preview_command(item.path, before, mode=mode, paths=scope_paths)
            execution = ProcessRunner().run(command, policy=IsolationPolicy(authoritative=False, fresh_worktree=False))
            observation = adapter.parse_execution(execution)
            raw = _plain(observation.attributes.get("raw_output", {}))
            analysis = raw.get("raw_analysis", {}) if isinstance(raw.get("raw_analysis"), dict) else {}
            after = source_tree_digest(item.path)
            record = {
                "index": index, "status": observation.status.value,
                "analysis_status": str(raw.get("semantic_status", raw.get("status", "UNKNOWN"))),
                "analysis_digest": str(analysis.get("analysis_digest", raw.get("analysis_digest", ""))),
                "source_consistent": bool(analysis.get("source", {}).get("source_consistent", False)),
                "snapshot_binding_valid": bool(raw.get("snapshot_binding_valid", False)),
                "source_unchanged": before == after == str(project.source.source_tree_digest),
                "error": raw.get("error"), "raw_output": raw,
            }
            if not record["source_unchanged"]:
                raise ValueError("Auto-Zoning modified or raced the pinned worktree")
            run_records.append(record)
            proposals.append(proposal_from_observation(observation))
    report = build_report(project=project, scope_mode=mode, scope_paths=scope_paths,
                          run_records=run_records, proposals=proposals)
    base = output_dir / f"{project_id}.zoning-preview.v1"
    _atomic_write(Path(str(base) + ".json"), canonical_json(report) + "\n")
    _atomic_write(Path(str(base) + ".md"), render_markdown(report))
    for record in run_records:
        _atomic_write(Path(str(base) + f".raw.run-{record['index']}.json"), canonical_json(record["raw_output"]) + "\n")
    return report
