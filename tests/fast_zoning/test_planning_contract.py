import json
import pytest
from benchmark_core.fast_zoning.planning import PlanValidationError, parse_plan_reply, planning_instruction


@pytest.fixture
def plan(tmp_path):
    (tmp_path/'a.py').write_text('value = 1\n')
    return {'likely_reads': ['a.py'], 'likely_writes': ['a.py'], 'diagnosis': 'Wrong boundary',
            'changes': ['Correct comparison'], 'tests': ['Boundary checks'],
            'evidence': [{'path': 'a.py', 'line': 1}]}


@pytest.mark.parametrize('fenced', [False, True])
def test_host_binds_distinct_ids_and_records_wire_format(plan, tmp_path, fenced):
    raw = json.dumps(plan)
    if fenced: raw = '```json\n' + raw + '\n```'
    before = (tmp_path/'a.py').read_bytes()
    result = parse_plan_reply(raw, task_id='ID-01', logical_task_id='logical-other', workspace=tmp_path)
    assert result['task_id'] == 'ID-01' and result['logical_task_id'] == 'logical-other'
    assert result['plan'] == plan and not result['write_authorized']
    assert result['wire_format'] == ('FENCED_JSON' if fenced else 'JSON')
    assert (tmp_path/'a.py').read_bytes() == before


@pytest.mark.parametrize('field', ['task_id', 'logical_task_id', 'schema', 'authority'])
def test_model_cannot_supply_routing_or_authority(plan, tmp_path, field):
    plan[field] = 'forged'
    with pytest.raises(PlanValidationError, match='FIELDS'):
        parse_plan_reply(json.dumps(plan), task_id='ID-01', workspace=tmp_path)


@pytest.mark.parametrize('suffix', ['}', '{}', '\nprose'])
def test_broken_json_is_not_repaired(plan, tmp_path, suffix):
    with pytest.raises(PlanValidationError, match='JSON_INVALID'):
        parse_plan_reply(json.dumps(plan) + suffix, task_id='ID-01', workspace=tmp_path)


@pytest.mark.parametrize('path', ['../a.py', '/a.py', '.git/config', '.autozoning/state',
                                  'a.py:stream', 'a.py/', './a.py', 'missing.py', 'a.py.'])
def test_paths_must_be_direct_existing_repository_files(plan, tmp_path, path):
    plan['likely_writes'] = [path]
    with pytest.raises(PlanValidationError):
        parse_plan_reply(json.dumps(plan), task_id='ID-01', workspace=tmp_path)


@pytest.mark.parametrize('line', [0, 2, True, '1'])
def test_evidence_line_is_checked(plan, tmp_path, line):
    plan['evidence'][0]['line'] = line
    with pytest.raises(PlanValidationError, match='LINE_INVALID'):
        parse_plan_reply(json.dumps(plan), task_id='ID-01', workspace=tmp_path)


def test_duplicate_keys_rejected(plan, tmp_path):
    raw = json.dumps(plan).replace('"diagnosis":', '"diagnosis":"old", "diagnosis":')
    with pytest.raises(PlanValidationError, match='DUPLICATE_FIELD'):
        parse_plan_reply(raw, task_id='ID-01', workspace=tmp_path)



def test_nonfinite_and_oversized_replies_reject(plan, tmp_path):
    raw = json.dumps(plan).replace('"line": 1', '"line": NaN')
    with pytest.raises(PlanValidationError, match='NONFINITE'):
        parse_plan_reply(raw, task_id='ID-01', workspace=tmp_path)
    with pytest.raises(PlanValidationError, match='SIZE'):
        parse_plan_reply(' ' * 65537, task_id='ID-01', workspace=tmp_path)


@pytest.mark.parametrize('field', ['changes', 'tests', 'evidence', 'likely_writes'])
def test_required_lists_cannot_be_empty(plan, tmp_path, field):
    plan[field] = []
    with pytest.raises(PlanValidationError):
        parse_plan_reply(json.dumps(plan), task_id='ID-01', workspace=tmp_path)


def test_instruction_never_asks_model_for_routing_ids():
    prompt = planning_instruction('Repair a boundary')
    assert 'exactly these six fields' in prompt
    assert 'Do not include schema, task_id or logical_task_id' in prompt
    assert prompt.endswith('Repair a boundary')


def test_duplicate_paths_and_nested_keys_reject(plan, tmp_path):
    plan['likely_reads'] *= 2
    with pytest.raises(PlanValidationError, match='DUPLICATE_PATH'):
        parse_plan_reply(json.dumps(plan), task_id='ID-01', workspace=tmp_path)
    plan['likely_reads'] = ['a.py']
    raw = json.dumps(plan).replace('"line": 1', '"line": 1, "line": 1')
    with pytest.raises(PlanValidationError, match='DUPLICATE_FIELD'):
        parse_plan_reply(raw, task_id='ID-01', workspace=tmp_path)
