from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import json
from pathlib import Path
from types import ModuleType
import sys

import pytest

from benchmark_core.assets import asset_path
from benchmark_core.manifest import load_project
from benchmark_core.result import RunStatus, SystemObservation
import cli.zoning_preview as preview
from cli.zoning_preview import build_report, proposal_from_observation, render_markdown
from suites.auto_zoning.adapters import ProductionSemanticSubprocessAdapter
from suites.auto_zoning.worker import main as worker_main

DIGEST = "sha256:" + "a" * 64


def _project():
    return load_project(asset_path("corpus/projects/pluggy.pinned_001.json"))


def test_preview_report_is_advisory_stable_and_telemetry_independent() -> None:
    raw = {
        "semantic_status": "PARTIAL", "snapshot_binding_valid": True,
        "raw_analysis": {"analysis_digest": DIGEST, "source": {"source_consistent": True},
                         "coverage": {"python_artifacts": 2, "parsed_files": 2}, "telemetry": {"seconds": 1}},
        "raw_projection": {"generated_at": "volatile", "zones": [{"zone_id": "z1"}]},
    }
    observation = SystemObservation(RunStatus.PASS, attributes={
        "proposal_mass": 0.5, "partial_mass": 0.25, "unknown_mass": 0.25,
        "ownership_proposal": (), "boundary_proposal": (), "raw_output": raw,
    })
    proposal = proposal_from_observation(observation)
    records = [{"index": index, "status": "PASS", "analysis_status": "PARTIAL",
                "analysis_digest": DIGEST, "source_consistent": True,
                "snapshot_binding_valid": True, "source_unchanged": True,
                "error": None, "raw_output": {"generated_at": str(index)}} for index in (1, 2)]
    report = build_report(project=_project(), scope_mode="FULL", scope_paths=(),
                          run_records=records, proposals=(proposal, proposal))
    assert report["status"] == "PASS"
    assert report["authority"] == "NONE" and report["advisory"] is True
    assert report["stability"]["stable"] is True
    assert report["stability"]["minimum_cozoning_pair_jaccard"] == 1.0
    assert "raw_output" not in report["runs"]["items"][0]
    assert "Advisory only" in render_markdown(report)


def test_preview_digest_ignores_nested_set_order() -> None:
    records = [{"status": "PASS", "analysis_digest": DIGEST, "source_consistent": True,
                "snapshot_binding_valid": True, "source_unchanged": True, "raw_output": {}}] * 2
    left = {"ownership": [], "boundaries": [], "zones": [{"zone_id": "z", "artifact_paths": ["a.py", "b.py"]}]}
    right = {"ownership": [], "boundaries": [], "zones": [{"zone_id": "z", "artifact_paths": ["b.py", "a.py"]}]}
    canonical_left = preview._semantic_canonical(left)
    canonical_right = preview._semantic_canonical(right)
    report = build_report(project=_project(), scope_mode="FULL", scope_paths=(), run_records=records,
                          proposals=(canonical_left, canonical_right))
    assert report["status"] == "PASS"
    assert report["stability"]["distinct_proposal_digests"] == 1


def test_preview_rejects_opaque_missing_analysis_digest() -> None:
    records = [{"status": "PASS", "analysis_digest": "", "source_consistent": True,
                "snapshot_binding_valid": True, "source_unchanged": True, "raw_output": {}}] * 2
    report = build_report(project=_project(), scope_mode="FULL", scope_paths=(),
                          run_records=records, proposals=({"x": 1}, {"x": 1}))
    assert report["status"] == "FAIL"
    assert report["proposal"] is None


def test_preview_adapter_emits_explicit_full_and_paths_contract(tmp_path: Path) -> None:
    adapter = ProductionSemanticSubprocessAdapter()
    full = json.loads(adapter.prepare_preview_command(tmp_path, DIGEST).stdin or "")
    assert full["analysis_scope"] == {"mode": "FULL", "paths": []}
    (tmp_path / "src").mkdir(); (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    paths = json.loads(adapter.prepare_preview_command(tmp_path, DIGEST, mode="PATHS", paths=("src/a.py",)).stdin or "")
    assert paths["analysis_scope"] == {"mode": "PATHS", "paths": ["src/a.py"]}
    with pytest.raises(ValueError, match="requires at least one"):
        adapter.prepare_preview_command(tmp_path, DIGEST, mode="PATHS")


def test_worker_distinguishes_full_from_legacy_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[object] = []
    autozoning = ModuleType("autozoning"); autozoning.__version__ = "0.6.0"
    semantic = ModuleType("autozoning.semantic")
    class Frontend:
        def analyze(self, repository: Path, seeds: object):
            calls.append(seeds)
            return {"status": "PARTIAL", "analysis_digest": DIGEST}
    semantic.RepositorySemanticFrontend = Frontend
    projection = ModuleType("autozoning.semantic.projection")
    projection.build_projection = lambda analysis: {}
    monkeypatch.setitem(sys.modules, "autozoning", autozoning)
    monkeypatch.setitem(sys.modules, "autozoning.semantic", semantic)
    monkeypatch.setitem(sys.modules, "autozoning.semantic.projection", projection)

    base = {"repository": str(tmp_path), "runner_input_fingerprint": DIGEST,
            "invocation": {"source_snapshot": {"input_fingerprint": DIGEST, "scope_paths": []},
                           "user_request": "preview"}}
    full = dict(base, schema="autonomous-dev-bench/auto-zoning-worker-request/v2",
                analysis_scope={"mode": "FULL", "paths": []})
    for payload in (full, base):
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
        output = StringIO(); monkeypatch.setattr(sys, "stdout", output)
        assert worker_main() == 0
        assert json.loads(output.getvalue())["status"] == "PARTIAL"
    assert calls == [None, []]


def test_run_project_preview_orchestrates_uncached_runs_and_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    production = tmp_path / "production"; (production / "autozoning" / "semantic").mkdir(parents=True)
    workspace = tmp_path / "workspace"; workspace.mkdir()
    project = _project()
    class Cache:
        def __init__(self, root): pass
        def ensure(self, repository, commit, *, expected_source_tree_digest):
            return object()
    class Manager:
        def __init__(self, root): pass
        @contextmanager
        def disposable(self, snapshot):
            yield type("Item", (), {"path": workspace})()
        def verify_pristine(self, item, *, expected_source_tree_digest): pass
    class Adapter:
        def __init__(self, **kwargs): pass
        def prepare_preview_command(self, repository, fingerprint, *, mode, paths): return object()
        def parse_execution(self, execution):
            raw = {"semantic_status": "PARTIAL", "snapshot_binding_valid": True,
                   "raw_analysis": {"analysis_digest": DIGEST, "source": {"source_consistent": True},
                                    "coverage": {"parsed_files": 29}, "files": []},
                   "raw_projection": {"zones": []}}
            return SystemObservation(RunStatus.PASS, attributes={"proposal_mass": 0.2, "partial_mass": 0.8,
                "unknown_mass": 0.0, "ownership_proposal": (), "boundary_proposal": (), "raw_output": raw})
    class Runner:
        def run(self, command, *, policy): return object()
    monkeypatch.setattr(preview, "SharedGitCache", Cache)
    monkeypatch.setattr(preview, "WorktreeManager", Manager)
    monkeypatch.setattr(preview, "ProductionSemanticSubprocessAdapter", Adapter)
    monkeypatch.setattr(preview, "ProcessRunner", Runner)
    monkeypatch.setattr(preview, "source_tree_digest", lambda path: str(project.source.source_tree_digest))
    output = tmp_path / "output"
    report = preview.run_project_preview("pluggy", production_source=production, python_executable=Path(sys.executable),
                                         cache_root=tmp_path / "cache", output_dir=output, runs=2)
    assert report["status"] == "PASS"
    assert (output / "pluggy.pinned_001.zoning-preview.v1.json").is_file()
    assert (output / "pluggy.pinned_001.zoning-preview.v1.md").is_file()
    assert (output / "pluggy.pinned_001.zoning-preview.v1.raw.run-2.json").is_file()


def test_preview_input_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown packaged"):
        preview.run_project_preview("unknown", production_source=tmp_path, python_executable=Path(sys.executable),
                                    cache_root=tmp_path, output_dir=tmp_path)
    production = tmp_path / "production"; (production / "autozoning" / "semantic").mkdir(parents=True)
    with pytest.raises(ValueError, match="at least 2"):
        preview.run_project_preview("pluggy", production_source=production, python_executable=Path(sys.executable),
                                    cache_root=tmp_path, output_dir=tmp_path, runs=1)
