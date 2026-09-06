from pathlib import Path
import shutil

import pytest

from benchmark_core.manifest import load_scenario
from benchmark_core.overlay import InvalidExperiment, ScenarioCheckpointMaterializer
from mutations import RECIPES


ROOT = Path(__file__).parents[2]


def test_checkpoint_materializer_applies_task_before_verified_mutation(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def call():\n    send()\n", encoding="utf-8")
    scenario = load_scenario(ROOT / "scenarios" / "synthetic" / "shared_provider_task.v1.json")
    order: list[str] = []
    materializer = ScenarioCheckpointMaterializer(
        overlay_handlers={
            "task:selftest.add_provider.v1": lambda root: order.append("task"),
            "fixture:title_provider": lambda root: order.append("fixture"),
        },
        mutation_recipes=RECIPES,
        mutation_parameters={
            "DUPLICATE_PROVIDER_DISPATCH": {"path": "target.py", "anchor": "    send()", "duplicate": "    send()"}
        },
    )
    materializer.apply(tmp_path, scenario, "candidate_bad_dispatch")
    assert order == ["task", "fixture"]
    assert (tmp_path / "target.py").read_text(encoding="utf-8").count("send()") == 2
    assert materializer.last_record is not None
    assert materializer.last_record.mutation_evidence[0].verified


def test_materializer_rejects_missing_hidden_mutation_parameters(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("pass\n", encoding="utf-8")
    scenario = load_scenario(ROOT / "scenarios" / "synthetic" / "shared_provider_task.v1.json")
    materializer = ScenarioCheckpointMaterializer(
        overlay_handlers={"task:selftest.add_provider.v1": lambda root: None, "fixture:title_provider": lambda root: None},
        mutation_recipes=RECIPES,
    )
    try:
        materializer.apply(tmp_path, scenario, "candidate_bad_dispatch")
    except (InvalidExperiment, ValueError):
        pass
    else:
        raise AssertionError("unproven mutation must invalidate the experiment")


def test_httpx_development_binding_materializes_verified_bad_candidate(tmp_path: Path) -> None:
    source = ROOT / ".cache" / "onboarding" / "httpx" / "httpx"
    if not source.is_dir():
        pytest.skip("optional pinned HTTPX onboarding checkout is unavailable")
    from corpus.adapters.httpx import HTTPX_DEVELOPMENT_BINDINGS as binding
    shutil.copytree(source, tmp_path / "httpx")
    scenario = load_scenario(ROOT / "scenarios" / "real_world" / "httpx.add_transport_provider.shared.v1.json")
    materializer = ScenarioCheckpointMaterializer(
        overlay_handlers=binding.overlay_handlers,
        mutation_recipes=binding.mutation_recipes,
        mutation_parameters=binding.mutation_parameters,
        mechanics_identities=binding.mechanics_identities,
    )
    candidate_root = tmp_path / "candidate"
    shutil.copytree(source, candidate_root / "httpx")
    candidate_record = materializer.apply(candidate_root, scenario, "candidate")
    assert not candidate_record.mutation_evidence
    record = materializer.apply(tmp_path, scenario, "candidate_bad_dispatch")
    assert record.mutation_evidence[0].verified
    client = (tmp_path / "httpx" / "_client.py").read_text(encoding="utf-8")
    assert client.count("transport_provider_registry.create(transport_provider, async_mode=False") == 2
    compile(client, "httpx/_client.py", "exec")
    assert "TransportProviderRegistry" in (tmp_path / "httpx/__init__.py").read_text(encoding="utf-8")
