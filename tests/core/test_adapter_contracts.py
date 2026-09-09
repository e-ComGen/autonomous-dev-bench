from __future__ import annotations

import sys

import pytest

from benchmark_core.adapter_contracts import (
    CommandSystemAdapter,
    SystemAdapter,
    require_command_system_adapter,
)
from suites.auto_refactoring import DesignFormServiceAdapter, ProductionCliAdapter


def test_subprocess_adapter_exposes_explicit_authoritative_capability() -> None:
    adapter = ProductionCliAdapter((sys.executable, "-c", "print('{}')"))

    assert isinstance(adapter, SystemAdapter)
    assert isinstance(adapter, CommandSystemAdapter)
    assert require_command_system_adapter(adapter) is adapter


def test_in_process_adapter_does_not_accidentally_claim_command_capability() -> None:
    adapter = DesignFormServiceAdapter(factory=lambda: object())

    assert isinstance(adapter, SystemAdapter)
    assert not isinstance(adapter, CommandSystemAdapter)
    with pytest.raises(TypeError, match="CommandSystemAdapter"):
        require_command_system_adapter(adapter)


def test_command_capability_requires_parse_prepare_and_binding() -> None:
    class IncompleteAdapter:
        adapter_id = "incomplete"
        adapter_version = "1"
        execution_boundary = "subprocess"

        def prepare_command(self, invocation, run_context):
            raise AssertionError("not executed")

    with pytest.raises(TypeError, match="CommandSystemAdapter"):
        require_command_system_adapter(IncompleteAdapter())
