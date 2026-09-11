from types import SimpleNamespace

import pytest

from suites.coding.adcp_dsh_binding import (
    DeepSeekBindingError,
    DeepSeekHarnessProtocol,
    DeepSeekRoleCommand,
)


class _Harness:
    def __init__(self, result):
        self.result = result

    def run(self, prompt, *, session_id):
        return self.result

    def close(self):
        pass


def _command():
    return DeepSeekRoleCommand(
        binding_id="deepseek-harness-sdk/0.1.2rc1:adcp-role-semantic-v1",
        call_id="zone:action:test",
        call_digest="a" * 64,
        actor_id="architect",
        role="LOCAL_ARCHITECT",
        input_json="{}",
        output_schema="fixture/1",
        instruction="return json",
        required_capabilities=("source.read", "evidence.read"),
        max_output_bytes=65536,
    )


def _protocol(tmp_path, result):
    return DeepSeekHarnessProtocol(
        state_root=tmp_path,
        base_url="http://127.0.0.1.invalid",
        api_key="fixture",
        require_installed_sdk=False,
        harness_factory=lambda **kwargs: _Harness(result),
    )


def test_max_tokens_is_a_settled_protocol_result_not_transport_uncertainty(tmp_path):
    protocol = _protocol(
        tmp_path,
        SimpleNamespace(final_response="partial untrusted output", finish_reason="max-tokens"),
    )

    result = protocol.run_agent(_command())

    assert result.finish_reason == "max-tokens"
    assert result.final_response == ""
    assert protocol.model_calls == 1


def test_completed_turn_still_requires_nonempty_root_response(tmp_path):
    protocol = _protocol(
        tmp_path,
        SimpleNamespace(final_response="", finish_reason="completed"),
    )

    with pytest.raises(DeepSeekBindingError, match="no committed root response"):
        protocol.run_agent(_command())
