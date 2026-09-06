from pathlib import Path

from tools.check_dependency_firewall import violations


def test_detects_production_import_of_benchmark(tmp_path: Path) -> None:
    (tmp_path / "production.py").write_text("from benchmark_core import ExperimentSpec\n", encoding="utf-8")
    assert "forbidden benchmark import" in violations(tmp_path)[0]


def test_detects_production_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = [\n  "autonomous-dev-bench>=1",\n]\n', encoding="utf-8"
    )
    assert "forbidden benchmark dependency" in violations(tmp_path)[0]


def test_detects_nested_legacy_dependency_manifests(tmp_path: Path) -> None:
    package = tmp_path / "packages" / "production"; package.mkdir(parents=True)
    (package / "setup.cfg").write_text("install_requires = benchmark-core>=1\n", encoding="utf-8")
    assert "setup.cfg: forbidden benchmark dependency" in violations(tmp_path)[0]


def test_detects_pep508_direct_reference(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("benchmark-core @ https://example.invalid/pkg.whl\n", encoding="utf-8")
    assert "forbidden benchmark dependency" in violations(tmp_path)[0]


def test_normal_production_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "production.py").write_text("from pathlib import Path\n", encoding="utf-8")
    assert violations(tmp_path) == []
