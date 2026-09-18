"""LAB dispatch contracts, with no model/provider invocation."""
import json
from pathlib import Path
import sys

import pytest

from benchmark_core.fast_zoning.manifest import InvalidManifest, digest_bytes, plan_digest, validate_manifest
from benchmark_core.fast_zoning.results import campaign_summary
from benchmark_core.fast_zoning.runner import execute_pair, plan_campaign
import benchmark_core.fast_zoning.runner as runner
import benchmark_core.fast_zoning.lab_backend as binding
from types import SimpleNamespace


@pytest.fixture
def lab_manifest(task_manifest, tmp_path):
    data = json.loads(task_manifest.read_text())
    artifact = tmp_path / 'lab-config.json'
    artifact.write_text('{}')
    binding = {'path': str(artifact), 'sha256': digest_bytes(artifact.read_bytes())}
    data['execution'] = {'route': 'LAB_HOST_ONLY', 'provider': 'deepseek', 'model': 'deepseek-v4-flash',
                         'thinking': 'EXISTING_PROVIDER_DEFAULT', 'native_tools': [],
                         'lab_root': str(tmp_path), 'python_executable': sys.executable,
                         'dependency_manifest': binding, 'config': binding,
                         'dsn_env_keys': {'A': 'LAB_TEST_DSN_A', 'B': 'LAB_TEST_DSN_B'}}
    for arm, policy in [('A', 'ordinary'), ('B', 'zone_preferred')]:
        packet = Path(data['contexts'][arm]['packet_path'])
        packet.write_text(json.dumps({'context_policy': policy}))
        data['contexts'][arm].update(packet_hash=digest_bytes(packet.read_bytes()), packet_bytes=packet.stat().st_size)
    task_manifest.write_text(json.dumps(data))
    return task_manifest


def result_for(manifest, treatment):
    return {'metrics': {'execution_success': True, 'model_executed': True, 'model_turns': 1,
                        'tool_calls': None, 'read_calls': None, 'provider_total_tokens': 3,
                        'packet_bytes': 9999, 'source_bytes': 8888, 'source_item_count': 7,
                        'total_wall_time': 11.0},
            'evaluation': {'evaluation_plan_digest': manifest['evaluation_plan_digest'],
                           'results': {row['id']: {'status': 'PASS'} for row in manifest['_evaluators']}},
            'patch_valid': True, 'lab_evidence': {'projection_validated': True, 'integrity_status': 'PASS'},
            'treatment': treatment, 'treatment_digest': plan_digest(treatment)}


def test_observability_follows_persistence_without_changing_primary(lab_manifest, tmp_path, monkeypatch):
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'observed-pair')
    events = []
    def export(directory):
        if directory.name in ('A', 'B'):
            assert (directory / 'metrics.json').is_file()
            events.append(directory.name)
        else:
            assert (directory / 'paired-summary.json').is_file()
            assert json.loads((directory / 'state.json').read_text())['status'] == 'COMPLETED'
            events.append('pair')
        raise RuntimeError('secret=must-not-leak')
    module = SimpleNamespace(__file__=str(tmp_path / 'exporter.py'),
                             export_run_profile=export, export_ab_profile=export)
    monkeypatch.setattr(binding, 'import_module', lambda name: module)
    calls = []
    def backend(**kwargs):
        calls.append(kwargs['arm'])
        return result_for(kwargs['manifest'], {'policy': kwargs['arm']})
    result = execute_pair(plan['pair_dir'], authorized=True, lab_backend=backend)
    assert result['status'] == 'COMPLETED'
    assert calls == plan['run_order']
    assert events == [*plan['run_order'], 'pair']
    for directory in [Path(plan['pair_dir']), *(Path(plan['pair_dir']) / arm for arm in ('A', 'B'))]:
        raw = (directory / 'observability-export-error.json').read_text()
        assert 'must-not-leak' not in raw
        assert json.loads(raw)['error_type'] == 'RuntimeError'


def test_observability_rejects_foreign_module_without_calling_it(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail('foreign exporter executed')
    monkeypatch.setattr(binding, 'import_module', lambda name: SimpleNamespace(
        __file__=str(tmp_path.parent / 'foreign.py'), export_run_profile=forbidden))
    result = binding.export_observability(manifest={'execution': {
        'python_executable': sys.executable, 'lab_root': str(tmp_path)}}, directory=tmp_path)
    assert result['status'] == 'EXPORT_ERROR'
    assert result['error_type'] == 'InvalidManifest'


@pytest.mark.parametrize('field,value', [('route', 'UNKNOWN'), ('native_tools', ['read']),
                                       ('model', 'other'), ('thinking', 'high')])
def test_unqualified_route_model_or_native_tools_rejected(lab_manifest, field, value):
    data = json.loads(lab_manifest.read_text())
    data['execution'][field] = value
    lab_manifest.write_text(json.dumps(data))
    with pytest.raises(InvalidManifest):
        validate_manifest(lab_manifest)


def test_lab_calls_fresh_arms_once_in_seeded_order_without_native_artifacts(lab_manifest, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('LAB must not execute or clone a native candidate')
    monkeypatch.setattr(runner, 'clone_snapshot', forbidden)
    monkeypatch.setattr(runner, '_execute', forbidden)
    monkeypatch.setattr(runner, 'capture_patch', forbidden)
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'pair-01')
    calls = []
    def backend(*, manifest, plan, arm, arm_dir):
        calls.append((arm, arm_dir))
        assert not (arm_dir / 'workspace').exists()
        policy = json.loads(Path(plan['arms'][arm]['packet_path']).read_text())
        return result_for(manifest, policy)
    result = execute_pair(plan['pair_dir'], authorized=True, lab_backend=backend)
    assert [arm for arm, _ in calls] == plan['run_order']
    assert calls[0][1] != calls[1][1]
    assert result['quality_comparison'] == 'EQUIVALENT_ON_PREDECLARED_EVALUATION'
    assert result['primary_result']['A']['packet_bytes'] == 9999
    assert result['primary_result']['A']['source_bytes'] == 8888
    assert result['primary_result']['A']['source_item_count'] == 7
    assert result['primary_result']['A']['total_wall_time'] == 11.0
    assert result['primary_result']['A']['policy_packet_bytes'] != 9999
    for _, arm_dir in calls:
        assert not (arm_dir / 'raw.jsonl').exists()
        assert not (arm_dir / 'patch.diff').exists()
        assert not (arm_dir / 'evaluation-workspace').exists()
    with pytest.raises(FileExistsError):
        execute_pair(plan['pair_dir'], authorized=True, lab_backend=backend)
    assert len(calls) == 2


@pytest.mark.parametrize('failure', ['raise', 'exit_only', 'missing_evidence', 'wrong_evaluators'])
def test_failed_lab_arm_does_not_suppress_other(lab_manifest, tmp_path, failure):
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'pair-01')
    calls = []
    def backend(*, manifest, plan, arm, arm_dir):
        calls.append(arm)
        if len(calls) == 1:
            if failure == 'raise':
                raise RuntimeError('offline failure')
            if failure == 'exit_only':
                return {'exit_code': 0}
            result = result_for(manifest, {'context_policy': 'ordinary'})
            if failure == 'wrong_evaluators':
                result['evaluation']['results'] = {'fabricated': {'status': 'PASS'}}
            else:
                del result['lab_evidence']
            return result
        return result_for(manifest, {'context_policy': 'zone_preferred'})
    result = execute_pair(plan['pair_dir'], authorized=True, lab_backend=backend)
    assert calls == plan['run_order']
    assert result['status'] == 'INFRA_FAILURE'
    assert result['primary_result'][calls[0]]['execution_success'] is False
    assert result['primary_result'][calls[0]]['model_executed'] is None
    assert result['primary_result'][calls[1]]['execution_success'] is True


def test_same_actual_treatment_is_excluded_from_comparison(lab_manifest, tmp_path):
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'pair-01')
    def backend(*, manifest, plan, arm, arm_dir):
        return result_for(manifest, {'context_policy': 'ordinary'})
    result = execute_pair(plan['pair_dir'], authorized=True, lab_backend=backend)
    assert result['comparison_eligible'] is False
    assert result['comparison_exclusion_reason'] == 'NO_DISTINCT_TREATMENT'
    assert result['quality_comparison'] == 'INCONCLUSIVE'
    assert result['resource_comparison']['equal_quality_cost_comparison'] == 'NOT_AVAILABLE'
    assert campaign_summary([result])['pairs_excluded'] == 1
    assert campaign_summary([result])['pairs_valid'] == 0


def test_lab_rejects_legacy_executor_before_claim(lab_manifest, tmp_path):
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'pair-01')
    with pytest.raises(InvalidManifest, match='executor hook'):
        execute_pair(plan['pair_dir'], authorized=True, executor=lambda *a: None)
    assert not (Path(plan['pair_dir']) / 'execution.claim').exists()


def test_stale_packet_quality_gate_rejected(lab_manifest):
    data = json.loads(lab_manifest.read_text())
    data['packet_quality_gate'] = {}
    lab_manifest.write_text(json.dumps(data))
    with pytest.raises(InvalidManifest, match='native packet quality'):
        validate_manifest(lab_manifest)


def test_missing_production_hook_fails_both_arms_without_native_fallback(lab_manifest, tmp_path, monkeypatch):
    import benchmark_core.fast_zoning.lab_backend as binding
    calls = []
    def missing(name):
        calls.append(name)
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(binding, 'import_module', missing)
    monkeypatch.delenv('ADCP_LAB_DEPENDENCY_MANIFEST', raising=False)
    plan = plan_campaign(lab_manifest, tmp_path / 'campaign', 'pair-01')
    assert calls == []
    result = execute_pair(plan['pair_dir'], authorized=True)
    assert calls == ['adcp_lab.runtime.fast_ab', 'adcp_lab.runtime.run_profile',
                     'adcp_lab.runtime.fast_ab', 'adcp_lab.runtime.run_profile',
                     'adcp_lab.runtime.ab_profile']
    assert result['status'] == 'INFRA_FAILURE'
    assert all(result['primary_result'][arm]['model_executed'] is None for arm in ('A', 'B'))
    state = json.loads((Path(plan['pair_dir']) / 'state.json').read_text())
    assert state['model_executed'] is None


@pytest.mark.parametrize('execution_success', [False, True])
def test_partial_projection_preserves_unknowns_only_for_failed_execution(lab_manifest, execution_success):
    from benchmark_core.fast_zoning.lab_backend import validate_result
    manifest = validate_manifest(lab_manifest)
    result = result_for(manifest, {'supplemental_facts': []})
    result['metrics'].update(execution_success=execution_success, model_executed=None)
    result['patch_valid'] = None
    result['lab_evidence'] = {'projection_validated': False, 'projection_error': 'MISSING_REPLAY',
                              'effect_integrity': 'UNKNOWN', 'ecacc': 'UNKNOWN'}
    if execution_success:
        with pytest.raises(InvalidManifest):
            validate_result(result, manifest)
    else:
        metrics, _, patch_valid = validate_result(result, manifest)
        assert metrics['model_executed'] is None
        assert patch_valid is None
        assert metrics['lab_evidence']['projection_error'] == 'MISSING_REPLAY'
