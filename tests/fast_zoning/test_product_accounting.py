"""Product tool names and explicit model failure must survive accounting."""
import json
import pytest
from benchmark_core.fast_zoning.events import parse_jsonl


def test_product_source_reads_are_counted(tmp_path):
    (tmp_path/'a.py').write_text('value = 1\n')
    events = []
    for i, (tool, error) in enumerate((('source.read', False), ('read', False), ('source.read', True))):
        events += [{'type': 'tool_execution_start', 'toolCallId': str(i),
                    'toolName': tool, 'args': {'path': 'a.py'}},
                   {'type': 'tool_execution_end', 'toolCallId': str(i),
                    'isError': error, 'result': {}}]
    result = parse_jsonl('\n'.join(map(json.dumps, events)).encode(), 0, tmp_path)
    assert result['read_calls'] == 3
    assert result['unique_files_read'] == 1
    assert result['exact_read_paths'][-1]['success'] is False


@pytest.mark.parametrize('stop', ['error', 'aborted', 'length', 'toolUse'])
def test_nonfinal_model_stop_is_not_execution_success(stop):
    events = [{'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': stop}},
              {'type': 'agent_end', 'isTerminal': True}]
    result = parse_jsonl('\n'.join(map(json.dumps, events)).encode(), 0)
    assert not result['execution_success']



def test_successful_fallback_retains_prior_failure_but_accepts_final_stop():
    events = [{'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': stop}}
              for stop in ('error', 'toolUse', 'stop')]
    events.append({'type': 'agent_end', 'isTerminal': True})
    result = parse_jsonl('\n'.join(map(json.dumps, events)).encode(), 0)
    assert result['execution_success']
    assert result['stop_reasons'] == ['error', 'toolUse', 'stop']


def test_missing_assistant_stop_is_not_a_confirmed_completion():
    events = [{'type': 'message_end', 'message': {'role': 'assistant'}},
              {'type': 'agent_end', 'isTerminal': True}]
    assert not parse_jsonl('\n'.join(map(json.dumps, events)).encode(), 0)['execution_success']
