"""Frozen v1 task contract. Validation never starts OMP."""
import hashlib
import json
from pathlib import Path
import re
from .gitops import git, verify_source

CATEGORIES = ('existing_suite', 'targeted_oracle', 'differential_check',
              'metamorphic_check', 'cross_component_check')
DEFAULT_EXECUTION = {'omp_executable': 'C:/Users/Venya/.bun/bin/omp.exe',
    'omp_version': '18.1.14', 'route': 'CLI_JSON',
    'model': 'alibaba-token-plan/deepseek-v4-pro', 'tools': 'read,edit,write',
    'max_time': '10m'}


class InvalidManifest(ValueError):
    pass


class PacketQualityPending(InvalidManifest):
    """Valid packet provenance lacks a separate quality admission record."""


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def plan_digest(value):
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode())


def run_order(seed):
    return ['A', 'B'] if int(digest_bytes(seed.encode()), 16) % 2 == 0 else ['B', 'A']


def _require(condition, message):
    if not condition:
        raise InvalidManifest(message)


def _artifact(base, value, expected):
    path = (base / value).resolve()
    _require(path.is_file(), f'missing artifact: {path}')
    _require(digest_bytes(path.read_bytes()) == expected, f'artifact hash mismatch: {path}')
    return str(path)


def validate_manifest(path):
    try:
        return _validate(Path(path).resolve())
    except InvalidManifest:
        raise
    except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
        raise InvalidManifest(str(exc)) from exc
    except Exception as exc:
        raise InvalidManifest(str(exc)) from exc


load_manifest = validate_manifest


def _validate(path, require_packet_quality=True):
    data = json.loads(path.read_text(encoding='utf-8'))
    required = {'schema_version', 'task_id', 'repo', 'clean_head', 'clean_tree',
        'buggy_head', 'buggy_tree', 'task_text', 'task_hash', 'evaluation_plan',
        'evaluation_plan_digest', 'run_order_seed', 'contexts', 'execution', 'model_executed'}
    _require(required <= data.keys(), 'missing required manifest fields')
    _require(set(data) <= required | {'evaluator_only', 'campaign_id', 'packet_quality_gate'}, 'unknown manifest field or per-arm override')
    if 'packet_quality_gate' in data:
        from .packet_import import validate_quality_gate
        validate_quality_gate(data, path.parent, require_qualified=require_packet_quality)
    _require(type(data['schema_version']) is int and data['schema_version'] == 1 and data['model_executed'] is False,
             'schema_version must be 1 and model_executed false')
    _require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', data['task_id']) is not None,
             'unsafe task_id')
    _require(isinstance(data['run_order_seed'], str) and bool(data['run_order_seed']), 'seed required')
    _require(isinstance(data['task_text'], str) and bool(data['task_text']), 'task text required')
    _require(digest_bytes(data['task_text'].encode()) == data['task_hash'], 'task hash mismatch')
    _require(set(data['execution']) == set(DEFAULT_EXECUTION), 'execution config fields mismatch')
    _require(data['execution'] == DEFAULT_EXECUTION, 'unqualified execution configuration')
    repo = (path.parent / data['repo']).resolve()
    for prefix in ('clean', 'buggy'):
        for suffix in ('head', 'tree'):
            _require(re.fullmatch('[0-9a-f]{40}', data[f'{prefix}_{suffix}']) is not None, 'invalid HEAD/TREE')
        _require(git(repo, 'rev-parse', data[f'{prefix}_head'] + '^{tree}').decode().strip()
                 == data[f'{prefix}_tree'], 'HEAD/TREE mismatch')
    verify_source(repo, data['buggy_head'], data['buggy_tree'])
    plan = data['evaluation_plan']
    _require(plan.get('phase') == 'PREDECLARED' and plan.get('frozen') is True, 'plan is not frozen predeclared')
    _require(plan.get('benchmark_head') == data['buggy_head'] and plan.get('benchmark_tree') == data['buggy_tree']
             and plan.get('task_hash') == data['task_hash'], 'plan benchmark/task binding mismatch')
    _require(plan_digest(plan) == data['evaluation_plan_digest'], 'evaluation digest mismatch')
    evaluators = plan['evaluators']
    _require(isinstance(evaluators, list) and bool(evaluators), 'evaluators required')
    _require({row['category'] for row in evaluators} == set(CATEGORIES), 'all evaluator categories must be declared')
    _require(len({row['id'] for row in evaluators}) == len(evaluators), 'duplicate evaluator id')
    _require(any(row.get('required') is True for row in evaluators), 'at least one required evaluator')
    resolved = []
    for row in evaluators:
        _require(isinstance(row['id'],str) and bool(row['id']), 'evaluator id missing')
        _require(isinstance(row['required'], bool), 'required must be boolean')
        _require(isinstance(row['command'], list) and bool(row['command']) and all(isinstance(x,str) for x in row['command']), 'invalid evaluator command')
        _require(isinstance(row['timeout_seconds'], (int,float)) and 0 < row['timeout_seconds'] <= 3600, 'invalid evaluator timeout')
        _require(isinstance(row['identity'], str) and bool(row['identity']), 'evaluator identity missing')
        _require(bool(row['artifacts']), 'hashed evaluator artifacts required')
        _require(any('{artifact0}' in part for part in row['command']),
                 'evaluator command must invoke its hash-bound artifact0')
        item = dict(row)
        item['artifacts'] = [{**a, 'path': _artifact(path.parent, a['path'], a['sha256'])} for a in row['artifacts']]
        resolved.append(item)
    forbidden = data.get('evaluator_only', {})
    _require(set(forbidden) <= {'forbidden_snippets', 'forbidden_artifacts'}, 'unknown evaluator-only metadata')
    needles = [s.encode() for s in forbidden.get('forbidden_snippets', [])]
    for artifact in forbidden.get('forbidden_artifacts', []):
        artifact_path = _artifact(path.parent, artifact['path'], artifact['sha256'])
        needles.append(Path(artifact_path).read_bytes())
    _require(all(needles), 'empty forbidden material')
    _require(set(data['contexts']) == {'A', 'B'}, 'two arm contexts required')
    contexts = {}
    for arm in ('A','B'):
        context = dict(data['contexts'][arm])
        fields = {'packet_path','packet_hash','packet_bytes','source_item_count','source_bytes'}
        optional = {'task_text','task_hash','zoning_time','planning_time','preprocessing_time'}
        if arm == 'B':
            fields.add('zoning')
        _require(fields <= context.keys() and set(context) <= fields | optional, 'context fields/per-arm override invalid')
        _require(context.get('task_text', data['task_text']) == data['task_text'] and context.get('task_hash',data['task_hash']) == data['task_hash'], 'A/B task mismatch')
        for field in ('packet_bytes','source_item_count','source_bytes'):
            _require(type(context[field]) is int and context[field] >= 0, f'invalid {field}')
        for field in ('zoning_time','planning_time','preprocessing_time'):
            if field in context and context[field] is not None:
                _require(type(context[field]) in (float,int) and context[field] >= 0, f'invalid {field}')
        context['packet_path'] = _artifact(path.parent, context['packet_path'], context['packet_hash'])
        packet = Path(context['packet_path']).read_bytes()
        _require(len(packet) == context['packet_bytes'], 'packet size mismatch')
        visible = data['task_text'].encode() + packet
        _require(not any(needle in visible for needle in needles), 'known hidden/gold material in model packet')
        _require(not any(label in visible.lower() for label in (b'hidden_root_cause', b'known_correct_patch', b'expected_fix_scope')), 'hidden metadata label in packet')
        if arm == 'B':
            zoning = context['zoning']
            _require(set(zoning) == {'zone_id','artifact_paths','snapshot_id','analysis_digest'}, 'zoning provenance fields missing')
            _require(all(zoning[k] for k in zoning), 'empty zoning provenance')
            _require(isinstance(zoning['zone_id'],str) and isinstance(zoning['snapshot_id'],str)
                     and re.fullmatch('[0-9a-f]{64}',zoning['analysis_digest']) is not None,
                     'invalid zoning identities')
            _require(isinstance(zoning['artifact_paths'],list), 'zoning artifact_paths must be list')
            for item in zoning['artifact_paths']:
                target = (repo / item).resolve()
                _require(not Path(item).is_absolute() and target.is_relative_to(repo) and target.exists(),
                         'missing or external zoning repository artifact')
        contexts[arm] = context
    return {**data, 'repo':str(repo), 'contexts':contexts, '_evaluators':resolved,
            '_manifest_path':str(path), '_manifest_hash':digest_bytes(path.read_bytes()),
            '_run_order':run_order(data['run_order_seed'])}
