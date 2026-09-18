"""Prepared oracle bindings reject changes without executing any oracle."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from benchmark_core.fast_zoning import qualification_evaluator as bridge


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    modules = tmp_path / 'native'
    shutil.copytree(Path(__file__).parent / 'fixtures/qualification_source', modules)
    oracle = tmp_path / 'oracle.py'
    oracle.write_bytes(b'raise AssertionError("validation must not execute")\n')
    source = {'evaluators': []}
    for category, (_, requirement) in bridge.CATEGORY_MAPPING.items():
        source[requirement] = True
        source['evaluators'].append({'id': category, 'category': category,
            'runner': 'frozen_oracle', 'oracle_path': str(oracle), 'oracle_sha256': digest(oracle)})
    origin = tmp_path / 'origin.json'
    origin.write_text(json.dumps(source), encoding='utf-8')
    rows = bridge.translate_evaluators(source, origin, modules, tmp_path / 'bound')
    options = {'interpreter': sys.executable, 'native_module_dir': modules,
               'native_module_paths': {name: str(modules / name) for name in bridge.SOURCE_MODULES}}
    return origin, digest(origin), rows, options


def verify(bundle):
    origin, expected, rows, options = bundle
    return bridge.verify_cache_plan_binding(origin, expected, rows, **options)


def rewrite_binding(bundle, mutate):
    rows = bundle[2]
    path = Path(rows[0]['artifacts'][1]['path'])
    data = json.loads(path.read_bytes())
    mutate(data)
    path.write_text(json.dumps(data), encoding='utf-8')
    for row in rows:
        row['artifacts'][1]['sha256'] = digest(path)


def test_roundtrip_is_read_only_and_never_executes_oracle(bundle, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('binding validation executed code or process')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(bridge, 'evaluate_binding', forbidden)
    root = bundle[0].parent
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert verify(bundle)['evaluators'][0]['id'] == 'EXISTING_SUITE'
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('field,value', [
    ('id', 'foreign'), ('category', 'targeted_oracle'), ('required', False),
    ('required', 1), ('identity', 'forged'), ('timeout_seconds', 301),
    ('command', ['foreign-python', '-B']), ('extra', True),
])
def test_row_contract_changes_reject(bundle, field, value):
    bundle[2][0][field] = value
    with pytest.raises(ValueError, match='CACHE_PLAN_ROWS'):
        verify(bundle)


@pytest.mark.parametrize('change', ['missing_row', 'extra_row', 'duplicate_row', 'reorder_rows',
    'missing_artifact', 'extra_artifact', 'duplicate_artifact', 'reorder_artifacts', 'alias_path', 'escape_path'])
def test_order_inventory_and_alias_changes_reject(bundle, change):
    rows = bundle[2]
    if change == 'missing_row': rows.pop()
    elif change == 'extra_row': rows.append(deepcopy(rows[0]) | {'id': 'extra'})
    elif change == 'duplicate_row': rows[1] = deepcopy(rows[0])
    elif change == 'reorder_rows': rows.reverse()
    else:
        artifacts = rows[0]['artifacts']
        if change == 'missing_artifact': artifacts.pop()
        elif change == 'extra_artifact': artifacts.append(deepcopy(artifacts[-1]))
        elif change == 'duplicate_artifact': artifacts[3] = deepcopy(artifacts[2])
        elif change == 'reorder_artifacts': artifacts[2], artifacts[3] = artifacts[3], artifacts[2]
        elif change == 'alias_path': artifacts[0]['path'] = str(Path(artifacts[0]['path']).parent / 'alias.py')
        else: artifacts[0]['path'] = str(Path(artifacts[0]['path']).parent / '..' / 'oracle.py')
    with pytest.raises(ValueError, match='CACHE_PLAN_'):
        verify(bundle)


@pytest.mark.parametrize('change', ['source', 'module_map', 'path_map', 'missing', 'extra', 'order', 'duplicate_id'])
def test_binding_cannot_self_declare_a_different_expected_inventory(bundle, change):
    def mutate(data):
        if change == 'source': data['source_plan']['extra'] = 'unbound'
        elif change == 'module_map': data['modules']['fast_ab.py'] = 'oracle_runner.py'
        elif change == 'path_map': data['paths']['EXISTING_SUITE']['oracle_path'] = 'qualification_evaluator.py'
        elif change == 'missing': data['artifacts'].pop()
        elif change == 'extra': data['artifacts'].append(deepcopy(data['artifacts'][0]))
        elif change == 'order': data['artifacts'].reverse()
        else: data['source_plan']['evaluators'][1]['id'] = data['source_plan']['evaluators'][0]['id']
    rewrite_binding(bundle, mutate)
    with pytest.raises(ValueError, match='CACHE_PLAN_'):
        verify(bundle)


@pytest.mark.parametrize('index', [0, 2, 3, 4, 5, 6])
def test_bound_adapter_modules_and_oracle_bytes_are_independently_pinned(bundle, index):
    target = Path(bundle[2][0]['artifacts'][index]['path'])
    target.write_bytes(target.read_bytes() + b'\n# changed\n')
    # Even updating candidate declarations cannot replace trusted expectations.
    for row in bundle[2]: row['artifacts'][index]['sha256'] = digest(target)
    with pytest.raises(ValueError, match='CACHE_PLAN_ARTIFACT_HASH'):
        verify(bundle)


@pytest.mark.parametrize('change', ['origin', 'origin_duplicate', 'binding_duplicate', 'native_input',
                                    'native_bytes', 'newline_only', 'native_shadow', 'native_missing'])
def test_origin_ambiguity_and_native_runtime_changes_reject(bundle, change, tmp_path):
    origin, expected, rows, options = bundle
    if change == 'origin': origin.write_bytes(origin.read_bytes() + b' ')
    elif change == 'origin_duplicate':
        origin.write_bytes(b'{"evaluators":[],"evaluators":[]}')
        expected = digest(origin)
    elif change == 'binding_duplicate':
        path = Path(rows[0]['artifacts'][1]['path'])
        path.write_bytes(b'{"source_plan":{},"source_plan":{}}')
    elif change == 'native_input': (tmp_path / 'oracle.py').write_bytes(b'changed')
    elif change in ('native_bytes', 'newline_only'):
        path = options['native_module_dir'] / 'fast_ab.py'
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n') if change == 'newline_only' else b'changed')
    elif change == 'native_shadow':
        other = tmp_path / 'shadow.py'
        shutil.copyfile(options['native_module_paths']['fast_ab.py'], other)
        options['native_module_paths']['fast_ab.py'] = str(other)
    else: options['native_module_paths'].pop('fast_ab.py')
    with pytest.raises(ValueError, match='CACHE_PLAN_'):
        bridge.verify_cache_plan_binding(origin, expected, rows, **options)


def test_symlinked_bound_file_rejects_even_identical_bytes(bundle, tmp_path):
    target = Path(bundle[2][0]['artifacts'][2]['path'])
    saved = tmp_path / 'saved.py'
    target.rename(saved)
    try: target.symlink_to(saved)
    except OSError: pytest.skip('host does not permit symlink creation')
    with pytest.raises(ValueError, match='CACHE_PLAN_LINK'):
        verify(bundle)
