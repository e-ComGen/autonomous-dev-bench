from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from benchmark_core.result import RunStatus
from mutations import (ApplicationEvidence, DUPLICATE_PROVIDER_DISPATCH, INTRODUCE_MUTABLE_GLOBAL,
                       UnsafeWorkspacePath, atomic_write_text)
from mutations.base import MutationDescriptor
from mutations.recipes import _TextRecipe


def test_atomic_write_rejects_traversal_and_absolute_paths(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    with pytest.raises(UnsafeWorkspacePath):
        atomic_write_text(tmp_path, "../outside.py", "bad")
    with pytest.raises(UnsafeWorkspacePath):
        atomic_write_text(tmp_path, outside, "bad")
    assert not outside.exists()


def test_descriptors_and_evidence_are_deeply_immutable() -> None:
    evidence = ApplicationEvidence("M", 1, "PASS", details={"items": [1]})
    with pytest.raises(FrozenInstanceError):
        evidence.seed = 2  # type: ignore[misc]
    assert evidence.details["items"] == (1,)


def test_seed_reproducibly_selects_and_mutates_same_target(tmp_path: Path) -> None:
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / "b.py").write_text("x = 1\n", encoding="utf-8")
    params = {"paths": ["b.py", "a.py"], "name": "shared", "literal": "[]"}
    first = INTRODUCE_MUTABLE_GLOBAL.apply(roots[0], params, seed=9182)
    second = INTRODUCE_MUTABLE_GLOBAL.apply(roots[1], params, seed=9182)
    assert first.status is RunStatus.PASS
    assert first.changed_paths == second.changed_paths
    assert (roots[0] / first.changed_paths[0]).read_bytes() == (roots[1] / second.changed_paths[0]).read_bytes()
    assert INTRODUCE_MUTABLE_GLOBAL.verify_applied(roots[0], first, params)


def test_recipe_preconditions_fail_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "provider.py"
    original = "dispatch()\ndispatch()\n"
    target.write_text(original, encoding="utf-8")
    evidence = DUPLICATE_PROVIDER_DISPATCH.apply(tmp_path, {"path": "provider.py", "anchor": "dispatch()"}, 4)
    assert evidence.status is RunStatus.INVALID_EXPERIMENT
    assert target.read_text(encoding="utf-8") == original


class NeverVerifiesRecipe(_TextRecipe):
    def _transform(self, original, parameters, seed):
        return original + "changed\n", {"token": "changed"}

    def _verify_text(self, text, details, parameters):
        return False


def test_failed_verify_applied_marks_experiment_invalid(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("before\n", encoding="utf-8")
    recipe = NeverVerifiesRecipe(MutationDescriptor("NEVER_VERIFY", "test", "exercise failure"))
    evidence = recipe.apply(tmp_path, {"path": "x.py"}, 7)
    assert evidence.status is RunStatus.INVALID_EXPERIMENT
    assert not evidence.verified
    assert "verify_applied failed" in evidence.details["reason"]
