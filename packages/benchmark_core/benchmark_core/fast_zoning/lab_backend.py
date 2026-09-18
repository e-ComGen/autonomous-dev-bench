"""Explicit LAB binding; functional results remain separate from LAB integrity evidence."""
from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import os
from pathlib import Path
import re
import sys
from typing import Protocol

from .manifest import InvalidManifest, digest_bytes, plan_digest
from .storage import write_json


class LabBackend(Protocol):
    def __call__(self, *, manifest: dict, plan: dict, arm: str, arm_dir: Path) -> dict:
        """Execute one fresh LAB arm and validate its evidence projection."""
        ...


def export_observability(*, manifest: dict, directory: Path, paired: bool = False) -> dict:
    """Best-effort derived export after durable primary results; never retry execution.

    Diagnostics intentionally omit exception text, paths and environment values.
    An unavailable/mismatched exporter does not change the recorded experiment.
    """
    try:
        config = manifest['execution']
        if Path(sys.executable).resolve() != Path(config['python_executable']).resolve():
            raise InvalidManifest('observability interpreter mismatch')
        module = import_module('adcp_lab.runtime.ab_profile' if paired else 'adcp_lab.runtime.run_profile')
        if not Path(module.__file__).resolve().is_relative_to(Path(config['lab_root']).resolve()):
            raise InvalidManifest('observability module outside bound LAB')
        exporter = module.export_ab_profile if paired else module.export_run_profile
        exporter(directory)
        return {'status': 'EXPORTED'}
    except Exception as exc:
        result = {'status': 'EXPORT_ERROR', 'error_type': type(exc).__name__,
                  'stage': 'pair' if paired else 'arm', 'primary_result_unchanged': True}
        try:
            write_json(directory / 'observability-export-error.json', result)
        except OSError:
            return {**result, 'diagnostic_persisted': False}
        return {**result, 'diagnostic_persisted': True}


def validate_execution(config: dict, base: Path) -> dict:
    expected = {'route', 'provider', 'model', 'thinking', 'native_tools', 'lab_root',
                'python_executable', 'dependency_manifest', 'config', 'dsn_env_keys'}
    fixed = {'route': 'LAB_HOST_ONLY', 'provider': 'deepseek', 'model': 'deepseek-v4-flash',
             'thinking': 'EXISTING_PROVIDER_DEFAULT', 'native_tools': []}
    if set(config) != expected or any(config.get(key) != value for key, value in fixed.items()):
        raise InvalidManifest('unqualified LAB execution configuration')
    result = deepcopy(config)
    for key in ('lab_root', 'python_executable'):
        path = (base / config[key]).resolve()
        if not (path.is_dir() if key == 'lab_root' else path.is_file()):
            raise InvalidManifest(f'missing LAB {key}')
        result[key] = str(path)
    for key in ('dependency_manifest', 'config'):
        artifact = config[key]
        if not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256'}:
            raise InvalidManifest(f'invalid LAB {key} binding')
        path = (base / artifact['path']).resolve()
        if not path.is_file() or digest_bytes(path.read_bytes()) != artifact['sha256']:
            raise InvalidManifest(f'LAB {key} hash mismatch')
        result[key] = {**artifact, 'path': str(path)}
    keys = config['dsn_env_keys']
    if (not isinstance(keys, dict) or set(keys) != {'A', 'B'}
            or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', v) for v in keys.values())
            or keys['A'] == keys['B']):
        raise InvalidManifest('LAB requires separately provisioned arm DSN environment keys')
    return result


def production_backend(*, manifest: dict, plan: dict, arm: str, arm_dir: Path) -> dict:
    """Load only the explicit LAB hook, from the bound runtime/interpreter."""
    config = manifest['execution']
    if Path(sys.executable).resolve() != Path(config['python_executable']).resolve():
        raise InvalidManifest('run FAST CLI with the bound LAB python_executable')
    key = 'ADCP_LAB_DEPENDENCY_MANIFEST'
    previous = os.environ.get(key)
    bound = config['dependency_manifest']['path']
    if previous is not None and Path(previous).resolve() != Path(bound).resolve():
        raise InvalidManifest('LAB dependency manifest environment mismatch')
    os.environ[key] = bound
    try:
        module = import_module('adcp_lab.runtime.fast_ab')
        origin = Path(module.__file__).resolve()
        if not origin.is_relative_to(Path(config['lab_root']).resolve()):
            raise InvalidManifest('LAB entry module is outside bound lab_root')
        return module.execute_arm(manifest=manifest, plan=plan, arm=arm, arm_dir=arm_dir)
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _check_treatment(value: object) -> None:
    if isinstance(value, dict):
        if {'arm', 'arm_id', 'arm_label'} & value.keys():
            raise InvalidManifest('treatment must exclude arm labels')
        for child in value.values():
            _check_treatment(child)
    elif isinstance(value, list):
        for child in value:
            _check_treatment(child)


def validate_result(result: dict, manifest: dict) -> tuple[dict, dict, bool | None]:
    required = {'metrics', 'evaluation', 'patch_valid', 'lab_evidence', 'treatment', 'treatment_digest'}
    if not isinstance(result, dict) or not required <= result.keys():
        raise InvalidManifest('missing structured LAB result fields')
    # Fail inside the per-arm boundary, before persistence can interrupt its peer.
    plan_digest(result)
    metrics, evaluation, evidence = result['metrics'], result['evaluation'], result['lab_evidence']
    if (not isinstance(metrics, dict) or 'model_executed' not in metrics or type(metrics.get('execution_success')) is not bool
            or (type(metrics.get('model_executed')) is not bool
                and not (metrics['execution_success'] is False and metrics.get('model_executed') is None))):
        raise InvalidManifest('LAB execution outcome must be explicit')
    for key in ('model_turns', 'tool_calls', 'read_calls'):
        if key not in metrics or (metrics[key] is not None and (type(metrics[key]) is not int or metrics[key] < 0)):
            raise InvalidManifest(f'invalid LAB observation: {key}')
    if type(result['patch_valid']) is not bool and not (metrics['execution_success'] is False and result['patch_valid'] is None):
        raise InvalidManifest('LAB patch validity must be explicit')
    if (not isinstance(evaluation, dict)
            or evaluation.get('evaluation_plan_digest') != manifest['evaluation_plan_digest']
            or not isinstance(evaluation.get('results'), dict)
            or set(evaluation['results']) != {row['id'] for row in manifest['_evaluators']}
            or any(not isinstance(row, dict) or row.get('status') not in {'PASS', 'FAIL', 'ERROR', 'NOT_RUN', 'NOT_REQUIRED'}
                   for row in evaluation['results'].values())):
        raise InvalidManifest('LAB functional evaluation does not match frozen plan')
    if (not isinstance(evidence, dict) or len(evidence) < 2
            or (evidence.get('projection_validated') is not True
                and not (metrics['execution_success'] is False and evidence.get('projection_validated') is False
                         and isinstance(evidence.get('projection_error'), str) and evidence['projection_error']))):
        raise InvalidManifest('LAB evidence projection was not validated')
    treatment = result['treatment']
    if not isinstance(treatment, dict) or not treatment:
        raise InvalidManifest('LAB treatment payload required')
    _check_treatment(treatment)
    if plan_digest(treatment) != result['treatment_digest']:
        raise InvalidManifest('LAB treatment digest mismatch')
    return {**metrics, 'lab_evidence': evidence, 'treatment': treatment,
            'treatment_digest': result['treatment_digest'], 'route': 'LAB_HOST_ONLY'}, evaluation, result['patch_valid']


def run_arm(backend: LabBackend, *, manifest: dict, plan: dict, arm: str, arm_dir: Path) -> tuple[dict, dict, bool | None]:
    try:
        return validate_result(backend(manifest=deepcopy(manifest), plan=deepcopy(plan), arm=arm, arm_dir=arm_dir), manifest)
    except Exception as exc:
        return ({'execution_success': False, 'model_executed': None, 'model_turns': None,
                 'tool_calls': None, 'read_calls': None, 'route': 'LAB_HOST_ONLY', 'error': str(exc)},
                {'evaluation_plan_digest': manifest['evaluation_plan_digest'],
                 'results': {row['id']: {'status': 'ERROR', 'error': str(exc)} for row in manifest['_evaluators']}}, None)
