import json

from benchmark_core.fast_zoning.events import parse_jsonl


def encode(events):
    return ("\n".join(json.dumps(event) for event in events)).encode()


def test_per_response_usage_sums_cached_input_not_final_cumulative():
    usage = [dict(input=12638, cacheRead=0, cacheWrite=0, output=94, totalTokens=12732),
             dict(input=458, cacheRead=12288, cacheWrite=0, output=114, totalTokens=12860)]
    result = parse_jsonl(encode([{"type": "message_end", "message": {"role": "assistant", "usage": u}} for u in usage] + [{"type": "agent_end", "isTerminal": True, "telemetry": {"input": 999}}]), 0)
    assert result["input_tokens"] == 13096
    assert result["cached_input_tokens"] == 12288
    assert result["provider_total_tokens"] == 25592
    assert result["output_tokens"] == 208
    assert result["reasoning_tokens"] is None
    assert result["model_turns"] == 2


def test_only_last_terminal_and_zero_exit_permit_execution_success():
    data = encode([{"type": "agent_end", "isTerminal": True}, {"type": "agent_end", "isTerminal": False}])
    assert not parse_jsonl(data, 0)["execution_success"]
    terminal = encode([{"type": "agent_end", "isTerminal": True}])
    assert not parse_jsonl(terminal, 1)["execution_success"]
    assert parse_jsonl(terminal, 0)["execution_success"]
    assert not parse_jsonl(terminal + b"\ninvalid", 0)["execution_success"]


def test_read_attempts_and_errors_retained_unique_successful_files(tmp_path):
    events = []
    for index, (path, error, details) in enumerate([
        ("src/a.py:4", False, {"resolvedPath": str(tmp_path / "src/a.py")}),
        ("src/a.py:12", False, {}), ("missing.py", True, {}),
        ("src", False, {"isDirectory": True})]):
        events += [{"type": "tool_execution_start", "toolCallId": str(index), "toolName": "read", "args": {"path": path, "intent": "inspect"}},
                   {"type": "tool_execution_end", "toolCallId": str(index), "isError": error, "result": {"details": details}}]
    result = parse_jsonl(encode(events), 0, tmp_path)
    assert result["tool_calls"] == result["read_calls"] == 4
    assert result["unique_files_read"] == 1
    assert result["exact_read_paths"][2]["success"] is False
    assert result["tools"][2]["error"] is not None


def test_absent_usage_is_unknown_and_malformed_json_reported():
    result = parse_jsonl(b'{"type":"message_end","message":{"role":"assistant"}}\n[]', None)
    assert result["input_tokens"] is None
    assert result["parse_errors"]
    assert result["total_cost"] is None


def test_partial_usage_never_silently_underreports_session():
    messages = [{"type":"message_end","message":{"role":"assistant","usage":{"input":12,"cacheRead":5,"cost":{"total":0}}}},
                {"type":"message_end","message":{"role":"assistant","usage":None}},
                {"type":"message_end","message":{"role":"user","usage":{"input":999}}}]
    result = parse_jsonl(encode(messages), 0)
    assert result["input_tokens"] is None
    assert result["cached_input_tokens"] is None
    assert result["provider_reported_cost"] is None
    assert result["model_turns"] == 2
