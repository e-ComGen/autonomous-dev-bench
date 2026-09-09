from __future__ import annotations

from pathlib import Path
import sys

import pytest

from benchmark_core.adapter_contracts import (
    CommandSystemAdapter,
    DeclaredProductionIdentity,
    SystemAdapter,
    require_command_system_adapter,
)
from benchmark_core.execution import CommandSpec, ExecutionResult
from benchmark_core.result import SystemObservation
from suites.auto_refactoring import DesignFormServiceAdapter, ProductionCliAdapter


def test_subprocess_adapter_exposes_explicit_authoritative_capability() -> None:
    adapter = ProductionCliAdapter((sys.executable, "-c", "print('{}')"))

    assert isinstance(adapter, SystemAdapter)
    assert isinstance(adapter, CommandSystemAdapter)
    assert isinstance(adapter, DeclaredProductionIdentity)
    assert require_command_system_adapter(adapter) is adapter


def test_in_process_adapter_does_not_accidentally_claim_command_capability() -> None:
    adapter = DesignFormServiceAdapter(factory=lambda: object())

    assert isinstance(adapter, SystemAdapter)
    assert not isinstance(adapter, CommandSystemAdapter)
    with pytest.raises(TypeError, match="CommandSystemAdapter"):
        require_command_system_adapter(adapter)


def test_command_capability_does_not_require_optional_production_identity() -> None:
    class InternalCommandAdapter:
        adapter_id = "internal-command"
        adapter_version = "1"

        def validate_system_binding(self, system, implementation_path: Path, executable_path: Path) -> bool:
            return True

        def prepare_command(self, invocation, run_context) -> CommandSpec:
            return CommandSpec((sys.executable, "-c", "pass"))

        def parse_execution(self, execution: ExecutionResult) -> SystemObservation:
            return SystemObservation("PASS")

    adapter = InternalCommandAdapter()
    assert isinstance(adapter, CommandSystemAdapter)
    assert not isinstance(adapter, DeclaredProductionIdentity)
    assert require_command_system_adapter(adapter) is adapter


def test_command_capability_requires_parse_prepare_and_binding() -> None:
    class IncompleteAdapter:
        adapter_id = "incomplete"
        adapter_version = "1"

        def prepare_command(self, invocation, run_context):
            raise AssertionError("not executed")

    with pytest.raises(TypeError, match="CommandSystemAdapter"):
        require_command_system_adapter(IncompleteAdapter())
