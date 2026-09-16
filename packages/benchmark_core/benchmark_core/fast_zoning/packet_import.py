"""Versioned packet provenance and a separate, explicit quality admission gate.

Quality evidence is an operator-issued artifact, not an inference from body counts.
This is integrity validation, not authentication of an adversarial operator.
"""
from __future__ import annotations

from copy import deepcopy
from functools import wraps
import json
from pathlib import Path
import shutil
from typing import Any

from .manifest import InvalidManifest, PacketQualityPending, digest_bytes, plan_digest
from .qualification_import import FROZEN_SOURCE, SourceContract, _binding, _require, _write

PACKET_SCHEMA = 'campaign-packet-set-v1'
QUALITY_SCHEMA = 'packet-quality-v1'


def _checked(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except InvalidManifest:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise InvalidManifest(str(exc)) from exc
    return checked


def copy_bundle_blocked(source: Path, output: Path) -> None:
    """A partial copy must never expose a formerly qualified execution document."""
    shutil.copytree(source, output, ignore=shutil.ignore_patterns('campaign-manifest.json'))
    blocked = _read(source / 'campaign-manifest.json')
    blocked['contexts'] = {}
    blocked.pop('packet_quality_gate', None)
    _write(output / 'campaign-manifest.json', blocked)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _hashed(base: Path, ref: dict[str, str]) -> bytes:
    path = (base / ref['path']).resolve()
    _require(path.is_relative_to(base.resolve()), 'packet artifact escapes bundle')
    payload = path.read_bytes()
    _require(digest_bytes(payload) == ref['sha256'], 'packet artifact hash mismatch')
    return payload


def _validate_evidence(evidence: dict[str, Any], packet_set: dict[str, Any]) -> None:
    _require(evidence.get('schema_version') == QUALITY_SCHEMA, 'unsupported quality evidence')
    _require(evidence.get('packet_set_digest') == plan_digest(packet_set), 'quality packet set mismatch')
    _require(evidence.get('task_hash') == packet_set['task_hash'], 'quality task mismatch')
    _require(evidence.get('arms') == {'A': 'PASS', 'B': 'PASS'}, 'both arms require quality PASS')
    _require(evidence.get('model_executed') is False, 'quality evidence must precede model execution')
    for key in ('reviewer_identity', 'criteria_identity'):
        _require(isinstance(evidence.get(key), str) and bool(evidence[key].strip()), 'quality evidence identity missing')


def validate_quality_gate(manifest: dict[str, Any], base: Path, *, require_qualified: bool = True) -> dict[str, Any]:
    gate = manifest['packet_quality_gate']
    _require(set(gate) == {'packet_set', 'quality_evidence'}, 'invalid packet quality gate')
    packet_set = json.loads(_hashed(base, gate['packet_set']))
    _require(packet_set['schema_version'] == PACKET_SCHEMA, 'unsupported packet set schema')
    for key in ('task_id', 'task_hash', 'buggy_head', 'buggy_tree', 'evaluation_plan_digest', 'run_order_seed'):
        _require(packet_set[key] == manifest[key], f'packet set binding mismatch: {key}')
    _require(packet_set['contexts'] == manifest['contexts'], 'packet set contexts mismatch')
    raw = json.loads(_hashed(base, packet_set['source_manifest'])) if packet_set.get('source_manifest') else None
    if raw is not None:
        _require(raw == packet_set['source_provenance'], 'source packet provenance changed')
        for key, value in {'TASK_ID': manifest['task_id'], 'TASK_SHA256': manifest['task_hash'],
                'TASK_TEXT': manifest['task_text'], 'BENCHMARK_HEAD': manifest['buggy_head'],
                'BENCHMARK_TREE': manifest['buggy_tree'], 'CLEAN_HEAD': manifest['clean_head'],
                'CLEAN_TREE': manifest['clean_tree'], 'MODEL_EXECUTED': False, 'TARGET_HINTS': [],
                'EVALUATION_PLAN_DIGEST': packet_set['source_evaluation_plan_digest']}.items():
            _require(raw.get(key) == value, f'packet provenance binding changed: {key}')
        for arm, context in manifest['contexts'].items():
            for source_field, target_field in [('PACKET_SHA256', 'packet_hash'), ('PACKET_BYTES', 'packet_bytes'),
                    ('SOURCE_ITEM_COUNT', 'source_item_count'), ('SOURCE_BYTES', 'source_bytes')]:
                _require(raw[f'{arm}_{source_field}'] == context[target_field], 'source packet metadata changed')
        zoning = manifest['contexts']['B']['zoning']
        _require(zoning == {'zone_id': raw['B_ZONE_ID'], 'artifact_paths': raw['B_ZONE_ARTIFACT_PATHS'],
            'snapshot_id': raw['B_SNAPSHOT_ID'], 'analysis_digest': raw['B_ANALYSIS_DIGEST'].removeprefix('sha256:')},
            'source zoning provenance changed')
    for context in manifest['contexts'].values():
        payload = _hashed(base, {'path': context['packet_path'], 'sha256': context['packet_hash']})
        _require(len(payload) == context['packet_bytes'], 'packet byte size mismatch')
    qualified = gate['quality_evidence'] is not None
    if qualified:
        _validate_evidence(json.loads(_hashed(base, gate['quality_evidence'])), packet_set)
    if require_qualified:
        if not qualified:
            raise PacketQualityPending('NO_PACKET_QUALITY: packet quality qualification required')
    return packet_set


def project_packet_envelope(envelope: dict[str, Any], bundle: Path, contexts: dict[str, Any]) -> dict[str, Any]:
    """Derive all readiness fields from immutable packet set and evidence bytes."""
    result = deepcopy(envelope)
    manifest = result['campaign_manifest']
    saved = _read(bundle / 'campaign-manifest.json')
    manifest['contexts'] = contexts
    manifest['packet_quality_gate'] = saved['packet_quality_gate']
    packet_set = validate_quality_gate(manifest, bundle, require_qualified=False)
    _require(packet_set['source_evaluation_plan_digest'] == result['source_evaluation_plan_digest'], 'source qualification digest changed')
    qualified = manifest['packet_quality_gate']['quality_evidence'] is not None
    result.update(packet_set_digest=plan_digest(packet_set), packet_set_version=packet_set['version'],
                  packets_imported=True, packet_quality_qualified=qualified,
                  execution_ready='YES' if qualified else 'NO_PACKET_QUALITY',
                  status='READY' if qualified else 'PACKETS_IMPORTED', missing_fields=[],
                  quality_missing_reason=None if qualified else 'NO_QUALIFICATION_EVIDENCE')
    result['campaign_manifest_digest'] = plan_digest(manifest)
    result['import_binding_digest'] = _binding(result)
    return result


def attach_context_set(bundle: Path, contexts: dict[str, Any], *, packet_version: str,
                       source_payload: bytes | None = None) -> dict[str, Any]:
    """Install packet bytes in an unpublished/new bundle; no quality inferred."""
    envelope = _read(bundle / 'import.json')
    manifest = envelope['campaign_manifest']
    previous = envelope.get('packet_set_digest')
    _require(isinstance(packet_version, str) and bool(packet_version.strip()), 'packet version required')
    if previous:
        _require(packet_version != envelope['packet_set_version'], 'replacement requires new packet version')
    retained = deepcopy(contexts)
    payloads = {}
    for arm in ('A', 'B'):
        context = retained[arm]
        payload = (bundle / context['packet_path']).resolve().read_bytes()
        _require(digest_bytes(payload) == context['packet_hash'] and len(payload) == context['packet_bytes'], 'packet hash/size mismatch')
        payloads[arm] = payload
    for arm, payload in payloads.items():
        target = bundle / 'packets' / f'{arm}_CONTEXT_PACKET'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        retained[arm]['packet_path'] = target.relative_to(bundle).as_posix()
    packet_set = {'schema_version': PACKET_SCHEMA, 'version': packet_version,
        'predecessor_digest': previous,
        **{key: manifest[key] for key in ('task_id', 'task_hash', 'buggy_head', 'buggy_tree', 'evaluation_plan_digest', 'run_order_seed')},
        'source_evaluation_plan_digest': envelope['source_evaluation_plan_digest'], 'contexts': retained,
        'source_manifest': None, 'source_provenance': None}
    if source_payload is not None:
        target = bundle / 'packets/source-manifest.json'
        target.write_bytes(source_payload)
        packet_set['source_manifest'] = {'path': 'packets/source-manifest.json', 'sha256': digest_bytes(source_payload)}
        packet_set['source_provenance'] = json.loads(source_payload)
    _write(bundle / 'packets/packet-set.json', packet_set)
    manifest['contexts'] = retained
    manifest['packet_quality_gate'] = {'packet_set': {'path': 'packets/packet-set.json',
        'sha256': digest_bytes((bundle / 'packets/packet-set.json').read_bytes())}, 'quality_evidence': None}
    _write(bundle / 'campaign-manifest.json', manifest)
    result = project_packet_envelope(envelope, bundle, retained)
    _write(bundle / 'import.json', result)
    return result


@_checked
def import_packet_manifest(bundle_dir: str | Path, source_manifest_path: str | Path,
                           source_root: str | Path, output_dir: str | Path, *, packet_version: str,
                           contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    from .qualification_import import validate_import
    envelope = validate_import(bundle_dir, contract=contract)
    manifest = envelope['campaign_manifest']
    source_payload = Path(source_manifest_path).read_bytes()
    raw = json.loads(source_payload)
    bindings = {'TASK_ID': manifest['task_id'], 'TASK_SHA256': manifest['task_hash'],
        'TASK_TEXT': manifest['task_text'], 'BENCHMARK_HEAD': manifest['buggy_head'],
        'BENCHMARK_TREE': manifest['buggy_tree'], 'CLEAN_HEAD': manifest['clean_head'],
        'CLEAN_TREE': manifest['clean_tree'], 'EVALUATION_PLAN_DIGEST': envelope['source_evaluation_plan_digest'],
        'MODEL_EXECUTED': False, 'TARGET_HINTS': [], 'PACKETS_READY': 'YES'}
    for key, value in bindings.items():
        _require(raw.get(key) == value, f'packet source binding mismatch: {key}')
    contexts = {}
    root = Path(source_root).resolve()
    for arm in ('A', 'B'):
        path = (root / raw[f'{arm}_PACKET_PATH']).resolve()
        _require(path.is_relative_to(root), 'source packet path escapes root')
        contexts[arm] = {'packet_path': str(path), 'packet_hash': raw[f'{arm}_PACKET_SHA256'],
            'packet_bytes': raw[f'{arm}_PACKET_BYTES'], 'source_item_count': raw[f'{arm}_SOURCE_ITEM_COUNT'],
            'source_bytes': raw[f'{arm}_SOURCE_BYTES'], 'planning_time': raw.get(f'{arm}_PLANNING_TIME'),
            'zoning_time': raw.get(f'{arm}_ZONING_TIME'), 'preprocessing_time': raw.get(f'{arm}_PREPROCESSING_TIME')}
    contexts['B']['zoning'] = {'zone_id': raw['B_ZONE_ID'], 'artifact_paths': raw['B_ZONE_ARTIFACT_PATHS'],
        'snapshot_id': raw['B_SNAPSHOT_ID'], 'analysis_digest': raw['B_ANALYSIS_DIGEST'].removeprefix('sha256:')}
    output = Path(output_dir).resolve()
    _require(not output.exists(), 'packet import destination already exists')
    copy_bundle_blocked(Path(bundle_dir), output)
    attach_context_set(output, contexts, packet_version=packet_version, source_payload=source_payload)
    return validate_import(output, contract=contract)


@_checked
def validate_packet_import(bundle_dir: str | Path, *, contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    from .qualification_import import validate_import
    result = validate_import(bundle_dir, contract=contract)
    _require(result.get('packets_imported') is True, 'no imported packet set')
    return result


@_checked
def qualify_packet_set(bundle_dir: str | Path, evidence_path: str | Path, output_dir: str | Path,
                       *, contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    """Explicit operator qualification; an old approval cannot approve replacement packets."""
    envelope = validate_packet_import(bundle_dir, contract=contract)
    source = Path(bundle_dir).resolve()
    packet_set = validate_quality_gate(envelope['campaign_manifest'], source, require_qualified=False)
    payload = Path(evidence_path).read_bytes()
    _validate_evidence(json.loads(payload), packet_set)
    output = Path(output_dir).resolve()
    _require(not output.exists(), 'qualification destination already exists')
    copy_bundle_blocked(source, output)
    (output / 'packets/quality-evidence.json').write_bytes(payload)
    manifest = envelope['campaign_manifest']
    manifest['packet_quality_gate']['quality_evidence'] = {'path': 'packets/quality-evidence.json', 'sha256': digest_bytes(payload)}
    _write(output / 'campaign-manifest.json', manifest)
    result = project_packet_envelope(envelope, output, manifest['contexts'])
    _write(output / 'import.json', result)
    return validate_packet_import(output, contract=contract)
