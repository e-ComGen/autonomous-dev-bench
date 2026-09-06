"""Platform-owned checkpoint and overlay materialization."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

from .identity import FrozenDict, Sha256Digest
from .scenario import ScenarioSpec


class InvalidExperiment(RuntimeError):
    pass


OverlayHandler = Callable[[Path], None]


@dataclass(frozen=True, slots=True)
class MaterializationRecord:
    checkpoint_id: str
    applied_overlays: tuple[str, ...]
    mutation_evidence: tuple[object, ...]
    mechanics_identities: Mapping[str, str]


class ScenarioCheckpointMaterializer:
    """Apply a checkpoint ancestry with task overlays before mutation overlays.

    Hidden mutation parameters are constructor-side evaluator input and never
    part of the SUT invocation.
    """

    def __init__(
        self,
        *,
        overlay_handlers: Mapping[str, OverlayHandler] | None = None,
        mutation_recipes: Mapping[str, object] | None = None,
        mutation_parameters: Mapping[str, Mapping[str, object]] | None = None,
        mechanics_identities: Mapping[str, str] | None = None,
    ) -> None:
        self.overlay_handlers = dict(overlay_handlers or {})
        self.mutation_recipes = dict(mutation_recipes or {})
        self.mutation_parameters = {key: dict(value) for key, value in (mutation_parameters or {}).items()}
        self.mechanics_identities = {key: str(Sha256Digest(value)) for key, value in (mechanics_identities or {}).items()}
        self.last_record: MaterializationRecord | None = None

    @staticmethod
    def file_overlay(files: Mapping[str, str | bytes]) -> OverlayHandler:
        frozen = tuple((path, value.encode("utf-8") if isinstance(value, str) else bytes(value)) for path, value in files.items())

        def apply(root: Path) -> None:
            base = root.resolve()
            for relative, payload in frozen:
                target = (base / relative).resolve()
                try: target.relative_to(base)
                except ValueError as exc: raise InvalidExperiment(f"overlay path escapes workspace: {relative}") from exc
                if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != base):
                    raise InvalidExperiment(f"overlay path crosses a symlink: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    try: os.unlink(temporary)
                    except FileNotFoundError: pass
        return apply

    def apply(self, workspace: Path, scenario: ScenarioSpec, checkpoint_id: str) -> MaterializationRecord:
        by_id = {item.checkpoint_id: item for item in scenario.checkpoints}
        if checkpoint_id not in by_id:
            raise InvalidExperiment(f"unknown checkpoint: {checkpoint_id}")
        ordered: list[object] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited: return
            checkpoint = by_id[name]
            for dependency in checkpoint.depends_on: visit(dependency)
            visited.add(name); ordered.append(checkpoint)

        visit(checkpoint_id)
        mutation_by_output = {item.output_checkpoint: item for item in scenario.mutations}
        applied: list[str] = []
        evidence: list[object] = []
        for checkpoint in ordered:
            for overlay_id in checkpoint.overlays:
                if overlay_id.startswith("mutation:"):
                    mutation = mutation_by_output.get(checkpoint.checkpoint_id)
                    mutation_id = overlay_id.split(":", 1)[1]
                    if mutation is None or mutation.mutation_id != mutation_id:
                        raise InvalidExperiment(f"mutation overlay is not bound to checkpoint: {overlay_id}")
                    recipe = self.mutation_recipes.get(mutation_id)
                    if recipe is None:
                        raise InvalidExperiment(f"no mutation recipe registered: {mutation_id}")
                    parameters = dict(mutation.parameters)
                    parameters.update(self.mutation_parameters.get(mutation_id, {}))
                    result = recipe.apply(workspace, parameters, mutation.seed)
                    if not getattr(result, "verified", False) or not recipe.verify_applied(workspace, result, parameters):
                        raise InvalidExperiment(f"mutation was not independently proven applied: {mutation_id}")
                    evidence.append(result)
                else:
                    try: handler = self.overlay_handlers[overlay_id]
                    except KeyError as exc: raise InvalidExperiment(f"no overlay handler registered: {overlay_id}") from exc
                    handler(workspace)
                applied.append(overlay_id)
        expected_mutations = {
            item.mutation_id for item in scenario.mutations if item.output_checkpoint in visited
        }
        applied_mutations = {getattr(item, "mutation_id", None) for item in evidence}
        if applied_mutations != expected_mutations:
            raise InvalidExperiment("selected checkpoint ancestry did not apply every declared mutation")
        expected_mechanics = scenario.metadata.get("mechanics_identities", {})
        actual_mechanics = {name: self.mechanics_identities.get(name) for name in applied}
        if expected_mechanics:
            expected_selected = {name: digest for name, digest in expected_mechanics.items() if name in applied}
            if actual_mechanics != expected_selected or any(value is None for value in actual_mechanics.values()):
                raise InvalidExperiment("overlay/mutation mechanics identity does not match the pinned scenario")
        record = MaterializationRecord(checkpoint_id, tuple(applied), tuple(evidence), FrozenDict(actual_mechanics))
        self.last_record = record
        return record
