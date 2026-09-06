from pathlib import Path
import hashlib
import pytest

from benchmark_core.bootstrap import ProjectEnvironmentBuilder
from benchmark_core.cas import FileSystemCAS
from benchmark_core.checkout import source_tree_digest
from benchmark_core.project import (
    BaselineSpec, BootstrapSpec, ClassificationSpec, CommandSpec, CorpusSpec, LegalSpec,
    PlatformSpec, ProjectSource, ProjectSpec, SecuritySpec,
)


def test_builder_creates_pinned_environment_and_green_baseline(tmp_path: Path) -> None:
    digest = "sha256:" + "1" * 64
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dependency = workspace / "requirements.txt"
    dependency.write_text("# intentionally empty\n", encoding="utf-8")
    dependency_digest = "sha256:" + hashlib.sha256(dependency.read_bytes()).hexdigest()
    source_digest = source_tree_digest(workspace)
    project = ProjectSpec(
        "bootstrap-selftest", "1", ProjectSource("local", "a" * 40, source_digest),
        LegalSpec("Apache-2.0", digest), PlatformSpec(("windows", "linux"), ("3.11",)),
        BootstrapSpec("python-standard", (dependency_digest,), ("requirements.txt",), ()),
        BaselineSpec((CommandSpec("smoke", ("python", "-c", "print('green')"), 30),)),
        ClassificationSpec("tiny", ("testing",)), SecuritySpec("package_indices_only", "none"),
        CorpusSpec("test", "development"),
    )
    result = ProjectEnvironmentBuilder(tmp_path / "envs", FileSystemCAS(tmp_path / "cas")).build_and_verify(project, workspace)
    assert result.admitted
    assert result.environment is not None
    assert result.baseline_health[0].result.stdout.strip() == "green"
    assert all(ref.startswith("cas:sha256:") for ref in result.evidence_refs)
