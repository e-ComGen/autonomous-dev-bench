"""Initial shared mutation catalogue; recipes create worlds, not suite verdicts."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from benchmark_core.result import RunStatus

from .base import ApplicationEvidence, MutationDescriptor, atomic_write_text, file_digest, safe_workspace_path, seeded_choice


def _string(parameters: Mapping[str, object], name: str, default: str | None = None) -> str:
    value = parameters.get(name, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _targets(parameters: Mapping[str, object]) -> tuple[str, ...]:
    value = parameters.get("path", parameters.get("paths"))
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)) and value and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise ValueError("path or non-empty paths must be supplied")


@dataclass(frozen=True, slots=True)
class _TextRecipe:
    descriptor: MutationDescriptor

    def _transform(self, original: str, parameters: Mapping[str, object], seed: int) -> tuple[str, Mapping[str, object]]:
        raise NotImplementedError

    def _verify_text(self, text: str, details: Mapping[str, object], parameters: Mapping[str, object]) -> bool:
        raise NotImplementedError

    def apply(self, workspace: str | Path, parameters: Mapping[str, object], seed: int = 0) -> ApplicationEvidence:
        candidates = _targets(parameters)
        chosen = seeded_choice(candidates, seed)
        path = safe_workspace_path(workspace, chosen, must_exist=True)
        before = file_digest(path)
        original = path.read_text(encoding="utf-8")
        preconditions = {"target_exists": True, "target_utf8": True}
        try:
            changed, details = self._transform(original, parameters, seed)
        except (ValueError, LookupError) as exc:
            return ApplicationEvidence(self.descriptor.mutation_id, seed, RunStatus.INVALID_EXPERIMENT,
                preconditions={**preconditions, "recipe_precondition": False}, details={"reason": str(exc), "path": chosen})
        atomic_write_text(workspace, chosen, changed)
        provisional = ApplicationEvidence(self.descriptor.mutation_id, seed, RunStatus.PASS, (chosen,),
            {chosen: before}, {chosen: file_digest(path)}, {**preconditions, "recipe_precondition": True}, {**details, "path": chosen})
        if not self.verify_applied(workspace, provisional, parameters):
            atomic_write_text(workspace, chosen, original)
            return ApplicationEvidence(self.descriptor.mutation_id, seed, RunStatus.INVALID_EXPERIMENT, (),
                provisional.before_digests, {chosen: file_digest(path)}, provisional.preconditions,
                {**details, "path": chosen, "reason": "independent verify_applied failed", "rolled_back": True})
        return provisional

    def verify_applied(self, workspace: str | Path, evidence: ApplicationEvidence, parameters: Mapping[str, object]) -> bool:
        if evidence.mutation_id != self.descriptor.mutation_id or len(evidence.changed_paths) != 1:
            return False
        try:
            path = safe_workspace_path(workspace, evidence.changed_paths[0], must_exist=True)
            digest_changed = file_digest(path) == evidence.after_digests[evidence.changed_paths[0]]
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".py":
                ast.parse(text)
            return digest_changed and evidence.before_digests[evidence.changed_paths[0]] != evidence.after_digests[evidence.changed_paths[0]] and self._verify_text(text, evidence.details, parameters)
        except (KeyError, OSError, UnicodeError, ValueError):
            return False


class DuplicateProviderDispatchRecipe(_TextRecipe):
    def __init__(self) -> None:
        super().__init__(MutationDescriptor(
            "DUPLICATE_PROVIDER_DISPATCH", "dispatch", "introduce a second provider dispatch at the same call boundary",
            precondition_ids=("unique_dispatch_anchor",), reversible=True,
            preserved_properties=("provider_call_shape",), intentionally_changed_properties=("dispatch_cardinality",)))

    def _transform(self, original: str, parameters: Mapping[str, object], seed: int) -> tuple[str, Mapping[str, object]]:
        anchor = _string(parameters, "anchor")
        if original.count(anchor) != 1:
            raise ValueError("anchor must occur exactly once")
        insertion = _string(parameters, "duplicate", anchor)
        token = f"# mutation-dispatch-{seed}"
        changed = original.replace(anchor, f"{anchor}\n{insertion}  {token}", 1)
        return changed, {"anchor": anchor, "insertion": insertion, "token": token}

    def _verify_text(self, text: str, details: Mapping[str, object], parameters: Mapping[str, object]) -> bool:
        return text.count(str(details["token"])) == 1 and str(details["insertion"]) in text


class IntroduceMutableGlobalRecipe(_TextRecipe):
    def __init__(self) -> None:
        super().__init__(MutationDescriptor(
            "INTRODUCE_MUTABLE_GLOBAL", "state", "introduce state with module-global mutable lifetime",
            precondition_ids=("python_module", "name_absent"), reversible=True,
            preserved_properties=("existing_source",), intentionally_changed_properties=("state_ownership", "state_lifetime")))

    def _transform(self, original: str, parameters: Mapping[str, object], seed: int) -> tuple[str, Mapping[str, object]]:
        name = _string(parameters, "name", f"_mutation_state_{seed:x}")
        if not name.isidentifier() or name in original:
            raise ValueError("global name must be a new Python identifier")
        literal = parameters.get("literal", "{}")
        if not isinstance(literal, str) or not literal.strip():
            raise ValueError("literal must be source text")
        expression = ast.parse(literal, mode="eval").body
        if not isinstance(expression, (ast.Dict, ast.List, ast.Set)):
            raise ValueError("literal must construct mutable list/dict/set state")
        statement = f"{name} = {literal}  # mutable-global-mutation-{seed}\n"
        return statement + original, {"name": name, "statement": statement.rstrip(), "token": f"mutable-global-mutation-{seed}"}

    def _verify_text(self, text: str, details: Mapping[str, object], parameters: Mapping[str, object]) -> bool:
        return text.count(str(details["token"])) == 1 and text.startswith(str(details["statement"]))


class CreateCrossZoneDependencyRecipe(_TextRecipe):
    def __init__(self) -> None:
        super().__init__(MutationDescriptor(
            "CREATE_CROSS_ZONE_DEPENDENCY", "dependency", "create a dependency edge across declared zones",
            precondition_ids=("source_module", "dependency_absent"), reversible=True,
            preserved_properties=("existing_source",), intentionally_changed_properties=("dependency_topology",)))

    def _transform(self, original: str, parameters: Mapping[str, object], seed: int) -> tuple[str, Mapping[str, object]]:
        module = _string(parameters, "module")
        if not all(part.isidentifier() for part in module.split(".")):
            raise ValueError("module must be a dotted Python identifier")
        alias = parameters.get("alias")
        if alias is not None and (not isinstance(alias, str) or not alias.isidentifier()):
            raise ValueError("alias must be a Python identifier")
        statement = f"import {module}" + (f" as {alias}" if alias else "")
        if statement in original:
            raise ValueError("dependency already exists")
        token = f"cross-zone-mutation-{seed}"
        line = f"{statement}  # {token}\n"
        return line + original, {"module": module, "statement": statement, "token": token,
            "source_zone": parameters.get("source_zone"), "target_zone": parameters.get("target_zone")}

    def _verify_text(self, text: str, details: Mapping[str, object], parameters: Mapping[str, object]) -> bool:
        return text.count(str(details["token"])) == 1 and text.startswith(str(details["statement"]))


DUPLICATE_PROVIDER_DISPATCH = DuplicateProviderDispatchRecipe()
INTRODUCE_MUTABLE_GLOBAL = IntroduceMutableGlobalRecipe()
CREATE_CROSS_ZONE_DEPENDENCY = CreateCrossZoneDependencyRecipe()

RECIPES = {recipe.descriptor.mutation_id: recipe for recipe in (
    DUPLICATE_PROVIDER_DISPATCH, INTRODUCE_MUTABLE_GLOBAL, CREATE_CROSS_ZONE_DEPENDENCY
)}
