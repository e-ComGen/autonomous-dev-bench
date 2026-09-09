"""Typed adapter capabilities used by benchmark orchestration.

The benchmark supports two intentionally different execution modes:

* non-authoritative adapters may invoke the system themselves;
* authoritative adapters must expose runner-owned command preparation,
  execution parsing, and production binding validation.

Keeping those contracts separate prevents optional capabilities from being
hidden behind ``getattr``/``callable`` checks and lets the runner depend on the
smallest interface required by each mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .execution import CommandSpec, ExecutionResult
from .experiment import SystemUnderTest
from .result import SystemObservation


@runtime_checkable
class AdapterIdentity(Protocol):
    adapter_id: str
    adapter_version: str


@runtime_checkable
class SystemAdapter(AdapterIdentity, Protocol):
    """Self-invoking adapter used by non-authoritative evaluation."""

    def invoke(self, invocation: Any, run_context: Any) -> SystemObservation: ...


@runtime_checkable
class SystemBindingValidator(AdapterIdentity, Protocol):
    """Capability that validates an exact production implementation binding."""

    def validate_system_binding(
        self,
        system: SystemUnderTest,
        implementation_path: Path,
        executable_path: Path,
    ) -> bool: ...


@runtime_checkable
class CommandSystemAdapter(SystemBindingValidator, Protocol):
    """Runner-owned subprocess capability required for authoritative runs."""

    def prepare_command(self, invocation: Any, run_context: Any) -> CommandSpec: ...

    def parse_execution(self, execution: ExecutionResult) -> SystemObservation: ...


@runtime_checkable
class DeclaredProductionIdentity(Protocol):
    """Optional stronger binding declared by production adapters that expose it."""

    production_system_id: str
    production_version: str


@runtime_checkable
class ReadOnlyAdapter(Protocol):
    """Optional cache-safety capability."""

    read_only: bool


def require_system_adapter(adapter: object) -> SystemAdapter:
    """Return the non-authoritative invocation capability or fail closed."""

    if not isinstance(adapter, SystemAdapter):
        raise TypeError("non-authoritative evaluation requires a SystemAdapter")
    return adapter


def require_command_system_adapter(adapter: object) -> CommandSystemAdapter:
    """Return the typed authoritative capability or fail before execution."""

    if not isinstance(adapter, CommandSystemAdapter):
        raise TypeError("authoritative evaluation requires a CommandSystemAdapter")
    return adapter
