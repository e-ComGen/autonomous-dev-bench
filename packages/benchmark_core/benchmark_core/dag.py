"""Content-addressed experiment DAG with deterministic topological ordering."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .identity import FrozenDict, Sha256Digest, freeze_json, require_identifier, require_unique


class CycleError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    action_id: str
    kind: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        require_identifier(self.action_id, "action_id")
        require_identifier(self.kind, "kind")
        require_identifier(self.version, "version")
        dependencies = tuple(self.dependencies)
        for dependency in dependencies:
            require_identifier(dependency, "dependency")
        require_unique(dependencies, "dependencies")
        object.__setattr__(self, "inputs", freeze_json(self.inputs))
        object.__setattr__(self, "dependencies", dependencies)

    def key(self, dependency_keys: Mapping[str, str] | None = None) -> str:
        keys = dependency_keys or {}
        missing = set(self.dependencies) - set(keys)
        if missing: raise KeyError(f"missing dependency keys: {sorted(missing)}")
        return str(Sha256Digest.of({"kind": self.kind, "version": self.version,
                                   "inputs": self.inputs,
                                   "dependencies": [(name, keys[name]) for name in sorted(self.dependencies)]}))

    action_key = key


class ExperimentDAG:
    def __init__(self, actions: Iterable[Action] = ()) -> None:
        self._actions: dict[str, Action] = {}
        for action in actions: self.add(action)

    def add(self, action: Action) -> None:
        if action.action_id in self._actions: raise ValueError(f"duplicate action: {action.action_id}")
        self._actions[action.action_id] = action

    @property
    def actions(self) -> Mapping[str, Action]: return dict(self._actions)

    def topological_order(self) -> tuple[Action, ...]:
        unknown = {dep for action in self._actions.values() for dep in action.dependencies if dep not in self._actions}
        if unknown: raise KeyError(f"unknown dependencies: {sorted(unknown)}")
        state: dict[str, int] = {}; result: list[Action] = []; stack: list[str] = []
        def visit(name: str) -> None:
            marker = state.get(name, 0)
            if marker == 2: return
            if marker == 1:
                start = stack.index(name); raise CycleError("cycle detected: " + " -> ".join(stack[start:] + [name]))
            state[name] = 1; stack.append(name)
            for dependency in sorted(self._actions[name].dependencies): visit(dependency)
            stack.pop(); state[name] = 2; result.append(self._actions[name])
        for name in sorted(self._actions): visit(name)
        return tuple(result)

    def action_keys(self) -> dict[str, str]:
        keys: dict[str, str] = {}
        for action in self.topological_order(): keys[action.action_id] = action.key(keys)
        return keys

DAG = ExperimentDAG
