from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from suites.coding.adcp_dsh_binding import (
    COMMAND_SCHEMA,
    DSH_BINDING_ID,
    DeepSeekBindingError,
    DeepSeekHarnessProtocol,
    DeepSeekRoleCommand,
    STOCK_PARITY_ENV,
    STOCK_PARITY_PROFILE,
)


def command() -> DeepSeekRoleCommand:
    return DeepSeekRoleCommand(
        binding_id=DSH_BINDING_ID,
        call_id="zone:action:test:1",
        call_digest="a" * 64,
        actor_id="adcp-test-coder",
        role="CODER",
        input_json='{"bounded":"context"}',
        output_schema="adcp.zone_development.ChangeProposal@2.0.0",
        instruction="Implement the requested change.",
        required_capabilities=("source.read", "evidence.read", "patch.propose"),
        max_output_bytes=4096,
    )


def test_binding_identity_is_versioned_for_worker_capability_change() -> None:
    assert DSH_BINDING_ID.endswith(":adcp-role-semantic-v2")
    assert COMMAND_SCHEMA == "autobench.adcp-dsh-command/2"
    assert STOCK_PARITY_PROFILE == "sdk"
    assert STOCK_PARITY_ENV == {
        "DSH_PERMISSION_MODE": "danger-full-access",
        "DSH_TELEMETRY_DISABLED": "1",
        "DSH_SESSION_STORE": "jsonl",
    }


def test_protocol_rejects_non_stock_worker_profile(tmp_path: Path) -> None:
    with pytest.raises(DeepSeekBindingError, match="match stock Harness profile"):
        DeepSeekHarnessProtocol(
            state_root=tmp_path,
            base_url="http://proxy.invalid/v1",
            api_key="proxy-token",
            profile="sdk-minimal",
            require_installed_sdk=False,
        )


def test_role_uses_host_disposable_workspace_and_stock_tool_env(tmp_path: Path) -> None:
    authoritative = tmp_path / "authoritative"
    authoritative.mkdir()
    (authoritative / "source.py").write_text("AUTHORITATIVE\n", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    captured: dict[str, object] = {}
    lifecycle: list[str] = []

    @contextmanager
    def role_workspace(_command: DeepSeekRoleCommand):
        sandbox.mkdir()
        (sandbox / "source.py").write_text("SNAPSHOT\n", encoding="utf-8")
        lifecycle.append("enter")
        try:
            yield sandbox
        finally:
            lifecycle.append("exit")

    class FakeHarness:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, prompt: str, *, session_id: str):
            lifecycle.append("run")
            cwd = Path(str(captured["cwd"]))
            assert cwd == sandbox.resolve()
            assert cwd.joinpath("source.py").read_text(encoding="utf-8") == "SNAPSHOT\n"
            # Demonstrate that normal Harness tools could mutate the disposable
            # worker workspace without touching ADCP's authoritative candidate.
            cwd.joinpath("scratch.txt").write_text("disposable\n", encoding="utf-8")
            assert "normal DeepSeek Harness tools" in prompt
            return SimpleNamespace(
                final_response='{"edits":[],"blockers":[{"kind":"REQUIREMENT","code":"NO_EDIT","detail":"fixture"}]}',
                finish_reason="completed",
                session_id=session_id,
            )

    protocol = DeepSeekHarnessProtocol(
        state_root=tmp_path / "state",
        base_url="http://proxy.invalid/v1",
        api_key="proxy-token",
        harness_factory=FakeHarness,
        role_workspace=role_workspace,
        require_installed_sdk=False,
    )
    result = protocol.run_agent(command())

    assert result.finish_reason == "completed"
    assert captured["profile"] == "sdk"
    assert captured["env"] == STOCK_PARITY_ENV
    assert lifecycle == ["enter", "run", "exit"]
    assert authoritative.joinpath("source.py").read_text(encoding="utf-8") == "AUTHORITATIVE\n"
    assert not authoritative.joinpath("scratch.txt").exists()
    assert sandbox.joinpath("scratch.txt").read_text(encoding="utf-8") == "disposable\n"


def test_fallback_workspace_remains_isolated_for_offline_qualification(tmp_path: Path) -> None:
    seen = {}

    class FakeHarness:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, _prompt: str, *, session_id: str):
            return SimpleNamespace(
                final_response='{"edits":[],"blockers":[{"kind":"REQUIREMENT","code":"NO_EDIT","detail":"fixture"}]}',
                finish_reason="completed",
                session_id=session_id,
            )

    protocol = DeepSeekHarnessProtocol(
        state_root=tmp_path / "state",
        base_url="http://proxy.invalid/v1",
        api_key="proxy-token",
        harness_factory=FakeHarness,
        require_installed_sdk=False,
    )
    protocol.run_agent(command())
    cwd = Path(str(seen["cwd"]))
    assert cwd.is_dir()
    assert cwd.is_relative_to((tmp_path / "state" / "isolated-role-workspaces").resolve())
