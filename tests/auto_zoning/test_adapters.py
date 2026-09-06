from __future__ import annotations

import sys
import types

import pytest

from benchmark_core.task import AutoZoningView
from suites.auto_zoning import ProductionSemanticAdapter, ProductionSemanticSubprocessAdapter, normalize_projection


def test_normalizer_preserves_partial_unknown_raw_and_never_authority() -> None:
    raw = {
        "assignments": [
            {"responsibility": "transport-provider", "owner": "transport", "confidence": .7},
            {"responsibility": "uncertain", "owner": None, "confidence": .3},
        ],
        "contracts": [{"from": "transport", "to": "client", "mass": .6}],
        "proposal_mass": .6,
        "partial_mass": .3,
        "unknown_mass": .1,
        "authoritative": True,
        "vendor": {"version": "0.6"},
    }
    result = normalize_projection(raw)
    assert result.proposal_mass == .6
    assert result.partial_mass == .3
    assert result.unknown_mass == .1
    assert result.authoritative is False
    assert result.raw_output["authoritative"] is True
    assert result.raw_fields["vendor"]["version"] == "0.6"
    assert len(result.ownership) == 1


def test_stale_source_is_invalid_not_a_capability_observation() -> None:
    result = normalize_projection({"status": "STALE_SOURCE", "process_status": "STALE_SOURCE"})
    assert result.observation().status.value == "INVALID_EXPERIMENT"
    assert result.unknown_mass == 1.0


def test_production_import_is_lazy_and_optional() -> None:
    adapter = ProductionSemanticAdapter("missing_autozoning.semantic")
    with pytest.raises(RuntimeError, match="optional autozoning"):
        adapter.run(".", {}, "request")


def test_fake_v06_frontend_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    calls: dict[str, object] = {}

    class FakeFrontend:
        def __init__(self) -> None:
            calls["constructed_without_repository"] = True

        def analyze(self, repository: object, **kwargs: object) -> object:
            calls["repository"] = repository
            calls["analysis_kwargs"] = kwargs
            return {"responsibility_to_zone": {"transport-provider": "transport"}, "status": "PARTIAL"}

    def build_projection(analysis: object) -> object:
        calls["analysis"] = analysis
        return {
            "proposal_mass": 1.0,
            "partial_mass": 0.0,
            "unknown_mass": 0.0,
            "status": "PROPOSED",
        }

    module = types.ModuleType("fake_autozoning.semantic")
    module.RepositorySemanticFrontend = FakeFrontend  # type: ignore[attr-defined]
    module.build_projection = build_projection  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_autozoning.semantic", module)
    result = ProductionSemanticAdapter("fake_autozoning.semantic").run(str(tmp_path), {"digest": "x"}, "add provider")
    assert calls["constructed_without_repository"] is True
    assert str(calls["repository"]) == str(tmp_path)
    assert calls["analysis_kwargs"] == {}
    assert calls["analysis"]["status"] == "PARTIAL"
    assert result.raw_fields["status"] == "PROPOSED"
    assert result.ownership[0].responsibility_id == "transport-provider"
    assert result.authoritative is False


def test_v06_distribution_is_disjoint_and_normalized() -> None:
    result = normalize_projection({
        "coverage": {"parse_index_coverage": .8, "responsibility_attribution_coverage": .75},
    })
    assert result.proposal_mass == pytest.approx(.6)
    assert result.partial_mass == pytest.approx(.2)
    assert result.unknown_mass == pytest.approx(.2)
    assert result.proposal_mass + result.partial_mass + result.unknown_mass == 1.0


def test_duplicate_responsibility_assignments_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate ownership assignment"):
        normalize_projection({
            "assignments": [
                {"responsibility_id": "r", "zone_id": "a"},
                {"responsibility_id": "r", "zone_id": "b"},
            ]
        })


def test_v06_boundaries_are_derived_from_resolved_facts() -> None:
    result = normalize_projection({
        "schema": "autozoning.semantic-analysis/v2",
        "responsibility_to_zone": {"r1": "z1", "r2": "z2"},
        "files": [{"assignments": [
            {"entity_id": "e1", "responsibility_id": "r1"},
            {"entity_id": "e2", "responsibility_id": "r2"},
        ]}],
        "facts": [{"subject": "e1", "targets": ["e2"], "status": "RESOLVED_LOCAL"}],
        "coverage": {"parse_index_coverage": 1.0, "responsibility_attribution_coverage": 1.0},
    })
    assert [(item.source_zone, item.target_zone) for item in result.boundaries] == [("z1", "z2")]


def test_invoke_uses_exact_empty_scope_and_runner_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    calls: dict[str, object] = {}

    class FakeFrontend:
        def analyze(self, repository: object, **kwargs: object) -> object:
            calls["kwargs"] = kwargs
            return {"responsibility_to_zone": {}, "coverage": {}, "status": "PARTIAL"}

    module = types.ModuleType("scoped_autozoning.semantic")
    module.RepositorySemanticFrontend = FakeFrontend  # type: ignore[attr-defined]
    module.build_projection = lambda analysis: {"status": "PROPOSED"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scoped_autozoning.semantic", module)
    fingerprint = "sha256:" + "a" * 64
    context = types.SimpleNamespace(workspace=tmp_path, input_fingerprint=fingerprint)
    observation = ProductionSemanticAdapter("scoped_autozoning.semantic").invoke(
        {"source_snapshot": {"input_fingerprint": fingerprint, "scope_paths": []}, "user_request": "inspect"},
        context,
    )
    assert calls["kwargs"] == {"seeds": []}
    assert observation.status.value == "PASS"


def test_invoke_fails_closed_on_runner_fingerprint_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    class FakeFrontend:
        def analyze(self, repository: object, **kwargs: object) -> object:
            return {"responsibility_to_zone": {}, "coverage": {}, "status": "PARTIAL"}

    module = types.ModuleType("bound_autozoning.semantic")
    module.RepositorySemanticFrontend = FakeFrontend  # type: ignore[attr-defined]
    module.build_projection = lambda analysis: {"status": "PROPOSED"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bound_autozoning.semantic", module)
    context = types.SimpleNamespace(workspace=tmp_path, input_fingerprint="sha256:" + "a" * 64)
    observation = ProductionSemanticAdapter("bound_autozoning.semantic").invoke(
        {"source_snapshot": {"input_fingerprint": "sha256:" + "b" * 64, "scope_paths": ["src/x.py"]}}, context,
    )
    assert observation.status.value == "INVALID_EXPERIMENT"


def test_invoke_requires_scope_paths(tmp_path: object) -> None:
    fingerprint = "sha256:" + "a" * 64
    context = types.SimpleNamespace(workspace=tmp_path, input_fingerprint=fingerprint)
    with pytest.raises(ValueError, match="scope_paths"):
        ProductionSemanticAdapter().invoke({"source_snapshot": {"input_fingerprint": fingerprint}}, context)


def test_prepare_command_accepts_public_view_and_preserves_scope(tmp_path: object) -> None:
    fingerprint = "sha256:" + "a" * 64
    view = AutoZoningView("inspect", {"input_fingerprint": fingerprint, "scope_paths": ["src/x.py"]})
    context = types.SimpleNamespace(workspace=tmp_path, input_fingerprint=fingerprint)
    command = ProductionSemanticSubprocessAdapter(command=(sys.executable, "worker.py")).prepare_command(view, context)
    request = __import__("json").loads(command.stdin)
    assert request["invocation"]["source_snapshot"]["scope_paths"] == ["src/x.py"]
    assert request["runner_input_fingerprint"] == fingerprint


@pytest.mark.parametrize("scope_paths", ["src/x.py", ["../x.py"], ["/x.py"], ["x.py", "x.py"], [1]])
def test_scope_contract_rejects_malformed_paths(tmp_path: object, scope_paths: object) -> None:
    fingerprint = "sha256:" + "a" * 64
    context = types.SimpleNamespace(workspace=tmp_path, input_fingerprint=fingerprint)
    with pytest.raises(ValueError):
        ProductionSemanticSubprocessAdapter().prepare_command(
            {"source_snapshot": {"input_fingerprint": fingerprint, "scope_paths": scope_paths}}, context
        )
