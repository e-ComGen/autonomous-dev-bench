from __future__ import annotations

import pytest

from benchmark_core.deepseek_v4_estimator import (
    DEEPSEEK_V4_MODEL,
    DEEPSEEK_V4_REVISION,
    DeepSeekV4RequestEstimator,
)
from benchmark_core.model_proxy import ExactTokenEstimateUnavailable


class RecordingEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, object]], str, str | None]] = []

    def __call__(self, messages, *, thinking_mode, reasoning_effort):
        self.calls.append((messages, thinking_mode, reasoning_effort))
        return "official-prompt"


class FixedTokenizer:
    def __init__(self, count: int = 17) -> None:
        self.count = count
        self.prompts: list[str] = []

    def encode(self, prompt: str):
        self.prompts.append(prompt)
        return list(range(self.count))


def _request(**overrides):
    request = {
        "model": DEEPSEEK_V4_MODEL,
        "messages": [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Fix the bug."},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 40,
        "temperature": 1.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request.update(overrides)
    return request


def test_estimator_uses_reference_encoder_and_tokenizer_for_exact_envelope() -> None:
    encoder = RecordingEncoder()
    tokenizer = FixedTokenizer(count=17)
    estimator = DeepSeekV4RequestEstimator(encoder, tokenizer)

    estimate = estimator.estimate(_request())

    assert estimate.input_tokens == 17
    assert estimate.max_output_tokens == 40
    assert estimate.max_total_tokens == 57
    assert tokenizer.prompts == ["official-prompt"]
    assert encoder.calls[0][1:] == ("thinking", "high")
    assert estimator.identity.revision == DEEPSEEK_V4_REVISION


def test_render_prompt_exposes_exact_reference_encoder_output_without_tokenizing() -> None:
    encoder = RecordingEncoder()
    tokenizer = FixedTokenizer(count=17)
    estimator = DeepSeekV4RequestEstimator(encoder, tokenizer)

    prompt = estimator.render_prompt(_request())

    assert prompt == "official-prompt"
    assert tokenizer.prompts == []
    assert encoder.calls[0][1:] == ("thinking", "high")


def test_top_level_tools_are_attached_to_system_anchor_like_reference_encoder_tests() -> None:
    encoder = RecordingEncoder()
    estimator = DeepSeekV4RequestEstimator(encoder, FixedTokenizer())
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a source file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]

    estimator.estimate(_request(tools=tools))

    messages = encoder.calls[0][0]
    assert messages[0]["tools"] == tools
    assert "tools" not in _request()["messages"][0]


def test_tool_history_and_reasoning_content_are_preserved_for_reference_encoder() -> None:
    encoder = RecordingEncoder()
    estimator = DeepSeekV4RequestEstimator(encoder, FixedTokenizer())
    messages = [
        {"role": "system", "content": "Use tools."},
        {"role": "user", "content": "Read x.py"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I should inspect the file.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"x.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "print('x')"},
        {"role": "user", "content": "Now fix it"},
    ]

    estimator.estimate(_request(messages=messages))

    assert encoder.calls[0][0] == messages


def test_assistant_tool_call_requires_nonempty_wire_id() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())
    messages = [
        {"role": "system", "content": "Use tools."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
    ]

    with pytest.raises(ExactTokenEstimateUnavailable, match="non-empty id"):
        estimator.estimate(_request(messages=messages))


def test_disabled_thinking_maps_to_reference_chat_mode() -> None:
    encoder = RecordingEncoder()
    estimator = DeepSeekV4RequestEstimator(encoder, FixedTokenizer())

    estimator.estimate(_request(thinking={"type": "disabled"}, reasoning_effort=None))

    assert encoder.calls[0][1:] == ("chat", None)


def test_missing_explicit_thinking_state_fails_closed() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())
    request = _request()
    request.pop("thinking")
    request.pop("reasoning_effort")

    with pytest.raises(ExactTokenEstimateUnavailable, match="explicit thinking state"):
        estimator.estimate(request)


def test_unknown_top_level_wire_field_fails_closed() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())

    with pytest.raises(ExactTokenEstimateUnavailable, match="unsupported DeepSeek-V4 wire field"):
        estimator.estimate(_request(extra_body={"mystery": True}))


def test_multimodal_content_fails_closed_for_text_only_paid_flash_arm() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())
    messages = [
        {"role": "system", "content": "text-only"},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    ]

    with pytest.raises(ExactTokenEstimateUnavailable, match="user content must be text"):
        estimator.estimate(_request(messages=messages))


def test_tool_request_without_system_or_developer_anchor_fails_closed() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    with pytest.raises(ExactTokenEstimateUnavailable, match="encoder anchor"):
        estimator.estimate(
            _request(messages=[{"role": "user", "content": "hi"}], tools=tools)
        )


def test_positive_max_tokens_is_required_for_pre_dispatch_envelope() -> None:
    estimator = DeepSeekV4RequestEstimator(RecordingEncoder(), FixedTokenizer())

    with pytest.raises(ExactTokenEstimateUnavailable, match="positive max_tokens"):
        estimator.estimate(_request(max_tokens=0))


def test_model_identity_mismatch_fails_before_encoding() -> None:
    encoder = RecordingEncoder()
    estimator = DeepSeekV4RequestEstimator(encoder, FixedTokenizer())

    with pytest.raises(ExactTokenEstimateUnavailable, match="model identity mismatch"):
        estimator.estimate(_request(model="other-model"))
    assert encoder.calls == []
