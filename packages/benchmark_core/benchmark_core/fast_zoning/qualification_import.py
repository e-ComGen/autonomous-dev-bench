"""Explicit, offline qualification-v1 to campaign-v1 provenance bridge.

Import validity is distinct from execution readiness. Source documents are read
from pinned Git objects, never regenerated or rewritten by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .gitops import git, verify_source
from .manifest import DEFAULT_EXECUTION, InvalidManifest, digest_bytes, plan_digest, run_order, validate_manifest

IMPORTER_VERSION = 'qualification-to-campaign-v1.0.0'
SOURCE_SCHEMA_VERSION = 'qualification-v1'
TARGET_SCHEMA_VERSION = 'campaign-schema-v1'
SOURCE_PREFIX = 'src/omp_zones/evaluation/expansion'


@dataclass(frozen=True)
class SourceContract:
    head: str
    tree: str
    evaluation_digests: dict[str, str]


FROZEN_SOURCE = SourceContract(
    '1bf2d27dbd4cabe2c9c95184f2a3631c11bd3c0d',
    'c33d3a11e36d7bafc5cfb6eb9bc2531f34a41c12', {
        'ID-01': '2e34fc19be661ac61a84af5c512ea48c4717ea51a2391ed037aa0bf34963b162',
        'ID-02': '4e887aa27003dbb4898ae4056d81859d0ce41b11abf491e2c5cfe606458e16ca',
        'ID-03': 'a6ce233072c245d9d3910935b3b3c9fd13976e3535db6ae6febcd71597137f51',
        'WZ-01': '130eabe0636464b901c64165576a5ba70788d462b704087e6c8d6e1995c83f9c',
        'WZ-02': '989028adba868ab3b4303654991c659d5a013c58bc34a2772ffe51f8cfe7db08',
        'WZ-03': 'b36af93e5216f1203a1da9f2801e0455dc70d95ec31594b6bcae260d761d7619'})

CATEGORY_MAP = {
    'EXISTING_SUITE': ('existing_suite', 'required_existing_suite'),
    'NARROW_ORACLE': ('targeted_oracle', 'required_targeted_oracle'),
    'TARGETED_ORACLE': ('targeted_oracle', 'required_targeted_oracle'),
    'DIFFERENTIAL_CHECK': ('differential_check', 'required_differential_checks'),
    'DIFFERENTIAL': ('differential_check', 'required_differential_checks'),
    'METAMORPHIC_CHECK': ('metamorphic_check', 'required_metamorphic_checks'),
    'METAMORPHIC': ('metamorphic_check', 'required_metamorphic_checks'),
    'CROSS_COMPONENT_CHECK': ('cross_component_check', 'required_cross_component_checks'),
    'CROSS_COMPONENT': ('cross_component_check', 'required_cross_component_checks'),
}


def source_plan_digest(plan: dict[str, Any]) -> str:
    """Qualification's original ASCII-escaping canonicalization, not campaign's."""
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidManifest(message)


def _read_object(repo: Path, head: str, name: str) -> bytes:
    return git(repo, 'show', f'{head}:{name}')


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + '\n', encoding='utf-8')


def _source_path(plan_path: str, relative: str) -> str:
    parts: list[str] = []
    _require(not PurePosixPath(relative).is_absolute() and '\\' not in relative,
             'invalid source artifact path')
    for part in (PurePosixPath(plan_path).parent / relative).parts:
        if part == '..':
            _require(bool(parts), 'source artifact escapes repository')
            parts.pop()
        elif part != '.':
            parts.append(part)
    return '/'.join(parts)


def required_evaluator_set(plan: dict[str, Any]) -> set[tuple[str, str, bool]]:
    rows = set()
    for row in plan['evaluators']:
        _require(row['category'] in CATEGORY_MAP, 'unknown source evaluator category')
        category, flag = CATEGORY_MAP[row['category']]
        _require(type(plan.get(flag)) is bool, 'source required evaluator flag missing')
        rows.add((row['id'], category, plan[flag]))
    _require(len(rows) == len(plan['evaluators']), 'duplicate source evaluator')
    _require(len({row['id'] for row in plan['evaluators']}) == len(rows), 'duplicate evaluator id')
    return rows


def _audit_source(source_repo: Path, benchmark_repo: Path, task_id: str,
                  contract: SourceContract) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    _require(task_id in contract.evaluation_digests, 'task not in frozen source contract')
    _require(git(source_repo, 'rev-parse', contract.head + '^{tree}').decode().strip() == contract.tree,
             'qualification HEAD/TREE mismatch')
    plan_path = f'{SOURCE_PREFIX}/{task_id}/evaluation-plan.json'
    ledger_bytes = _read_object(source_repo, contract.head, f'{SOURCE_PREFIX}/readiness.json')
    plan_bytes = _read_object(source_repo, contract.head, plan_path)
    qualification = json.loads(ledger_bytes)[task_id]
    plan = json.loads(plan_bytes)
    _require(plan.get('schema_version') == 1 and plan.get('phase') == 'PREDECLARED', 'unsupported or non-predeclared source')
    expected = contract.evaluation_digests[task_id]
    _require(source_plan_digest(plan) == expected == qualification['EVALUATION_PLAN_DIGEST'], 'source evaluation digest mismatch')
    _require(qualification.get('TASK_EXECUTION_READY') == 'YES' and qualification.get('MODEL_EXECUTED') is False
             and qualification.get('KNOWN_FIX_RESET') == 'YES', 'source qualification incomplete')
    _require(qualification['TASK_ID'] == task_id and qualification['TASK_TEXT'] == plan['task_text'], 'source task mismatch')
    _require(digest_bytes(plan['task_text'].encode()) == plan['task_sha256'] == qualification['TASK_HASH'], 'source task hash mismatch')
    _require(plan.get('target_hints') == [] and qualification.get('TARGET_HINTS') == [], 'unexpected target hints')
    for prefix, source_prefix in [('CLEAN', 'reference'), ('BUGGY', 'benchmark')]:
        head, tree = qualification[f'{prefix}_HEAD'], qualification[f'{prefix}_TREE']
        _require(plan[f'{source_prefix}_head'] == head and plan[f'{source_prefix}_tree'] == tree, 'source benchmark binding mismatch')
        _require(git(benchmark_repo, 'rev-parse', head + '^{tree}').decode().strip() == tree, 'benchmark HEAD/TREE mismatch')
    verify_source(benchmark_repo, qualification['BUGGY_HEAD'], qualification['BUGGY_TREE'])
    _require(git(benchmark_repo, 'rev-list', '--parents', '-n', '1', qualification['BUGGY_HEAD']).decode().split()
             == [qualification['BUGGY_HEAD'], qualification['CLEAN_HEAD']], 'buggy parent must equal clean HEAD')
    required = required_evaluator_set(plan)
    _require(any(row[2] for row in required), 'no required source evaluators')
    for phase, expected_status in [('clean', 'PASS'), ('known-fix', 'PASS')]:
        evidence = qualification['EVALUATIONS'][phase]['EVALUATOR_STATUS']
        _require(all(evidence.get(identity) == expected_status for identity, _, needed in required if needed), 'qualification evaluator evidence incomplete')
    buggy_evidence = qualification['EVALUATIONS']['buggy']['EVALUATOR_STATUS']
    _require(any(buggy_evidence.get(identity) == 'FAIL' for identity, _, needed in required if needed), 'buggy qualification does not fail')
    objects = {plan_path: plan_bytes, f'{SOURCE_PREFIX}/readiness.json': ledger_bytes}
    for row in plan['evaluators']:
        for key, value in row.items():
            if key.endswith('_path'):
                hash_key = key[:-5] + '_sha256'
                _require(hash_key in row, 'unhashed source evaluator artifact')
                name = _source_path(plan_path, value)
                blob = _read_object(source_repo, contract.head, name)
                _require(digest_bytes(blob) == row[hash_key], 'source evaluator artifact hash mismatch')
                objects[name] = blob
    # Runtime adapters are pinned source code; importing them never invokes a model.
    from .qualification_evaluator import SOURCE_MODULES
    for module in SOURCE_MODULES:
        name = 'src/omp_zones/' + module
        objects[name] = _read_object(source_repo, contract.head, name)
    return plan, qualification, objects


def _binding(envelope: dict[str, Any]) -> str:
    return plan_digest({key: envelope[key] for key in ('source_evaluation_plan_digest', 'task_hash',
        'translated_evaluator_identities', 'campaign_manifest_digest', 'importer_version')})


def _check_packet_privacy(contexts: dict[str, Any], output: Path, qualification: dict[str, Any]) -> None:
    private_values = [qualification.get(key) for key in
                      ('HIDDEN_ROOT_CAUSE', 'KNOWN_CORRECT_FIX', 'KNOWN_CORRECT_PATCH', 'EXPECTED_FIX_SCOPE')]
    for context in contexts.values():
        packet = (output / context['packet_path']).resolve().read_bytes()
        _require(not any(isinstance(secret, str) and secret and secret.encode() in packet
                         for secret in private_values), 'private qualification material in packet')


def import_qualification(source_repo: str | Path, benchmark_repo: str | Path, task_id: str,
                         output_dir: str | Path, *, run_order_seed: str,
                         contexts: dict[str, Any] | None = None,
                         contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    """Create a new immutable import bundle; never create context packets."""
    from .qualification_evaluator import translate_evaluators

    source_repo, benchmark_repo, output = Path(source_repo).resolve(), Path(benchmark_repo).resolve(), Path(output_dir).resolve()
    _require(not output.exists(), 'import destination already exists')
    _require(isinstance(run_order_seed, str) and bool(run_order_seed), 'run order seed required')
    plan, qualification, objects = _audit_source(source_repo, benchmark_repo, task_id, contract)
    source_root = output / 'private' / 'source'
    for name, blob in objects.items():
        target = source_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    _write(output / 'private' / 'qualification.json', qualification)
    source_plan_path = source_root / SOURCE_PREFIX / task_id / 'evaluation-plan.json'
    rows = translate_evaluators(plan, source_plan_path, source_root / 'src/omp_zones', output / 'private/evaluators')
    _require({(r['id'], r['category'], r['required']) for r in rows} == required_evaluator_set(plan), 'translated evaluator set mismatch')
    for row in rows:
        for artifact in row['artifacts']:
            artifact['path'] = Path(artifact['path']).resolve().relative_to(output).as_posix()
    campaign_plan = {'phase': 'PREDECLARED', 'frozen': True, 'benchmark_head': plan['benchmark_head'],
                     'benchmark_tree': plan['benchmark_tree'], 'task_hash': plan['task_sha256'], 'evaluators': rows}
    manifest = {'schema_version': 1, 'task_id': task_id, 'repo': str(benchmark_repo),
        'clean_head': plan['reference_head'], 'clean_tree': plan['reference_tree'],
        'buggy_head': plan['benchmark_head'], 'buggy_tree': plan['benchmark_tree'],
        'task_text': plan['task_text'], 'task_hash': plan['task_sha256'],
        'evaluation_plan': campaign_plan, 'evaluation_plan_digest': plan_digest(campaign_plan),
        'run_order_seed': run_order_seed, 'contexts': contexts or {},
        'execution': dict(DEFAULT_EXECUTION), 'model_executed': False}
    _write(output / 'campaign-manifest.json', manifest)
    if contexts is not None:
        _check_packet_privacy(contexts, output, qualification)
        validate_manifest(output / 'campaign-manifest.json')
    refs = {'repo': str(source_repo), 'head': contract.head, 'tree': contract.tree,
            'plan_path': f'{SOURCE_PREFIX}/{task_id}/evaluation-plan.json',
            'readiness_path': f'{SOURCE_PREFIX}/readiness.json'}
    public = {key: manifest[key] for key in ('task_id', 'buggy_head', 'buggy_tree', 'task_text', 'task_hash')}
    request = {'schema_version': 'packet-build-request-v1', **public, 'target_hints': [],
        'source_qualification_refs': {**refs, 'source_evaluation_plan_digest': contract.evaluation_digests[task_id]},
        'policies': {'A': 'normal non-zoned ContextPlanner', 'B': 'real Auto-Zoning -> zone-aware ContextPlanner'},
        'expected_outputs': {'A': ['packet_path', 'packet_hash', 'packet_bytes', 'source_item_count', 'source_bytes'],
                             'B': ['packet_path', 'packet_hash', 'packet_bytes', 'source_item_count', 'source_bytes', 'zoning']},
        'output_schema': json.loads(Path(__file__).with_name('packet-build-output.v1.schema.json').read_text(encoding='utf-8')),
        'model_execution_allowed': False}
    _write(output / 'packet-build-request.json', request)
    _write(output / 'model-visible-task.json', public)
    envelope = {'importer_version': IMPORTER_VERSION, 'source_schema_version': SOURCE_SCHEMA_VERSION,
        'target_schema_version': TARGET_SCHEMA_VERSION, 'task_id': task_id, 'task_hash': plan['task_sha256'],
        'source_refs': refs, 'source_evaluation_plan_digest': contract.evaluation_digests[task_id],
        'campaign_manifest_digest': plan_digest(manifest),
        'translated_evaluator_identities': [{'id': r['id'], 'category': r['category'], 'required': r['required'], 'identity': r['identity']} for r in rows],
        'campaign_manifest': manifest, 'model_visible_manifest': public,
        'run_order': run_order(run_order_seed), 'source_import_valid': True,
        'execution_ready': 'YES' if contexts is not None else 'NO_MISSING_PACKETS',
        'status': 'READY' if contexts is not None else 'IMPORTED_NOT_EXECUTABLE',
        'missing_fields': [] if contexts is not None else ['A_PACKET_PATH', 'A_PACKET_HASH', 'B_PACKET_PATH', 'B_PACKET_HASH']}
    envelope['import_binding_digest'] = _binding(envelope)
    _write(output / 'import.json', envelope)
    return envelope


def validate_import(bundle_dir: str | Path, *, contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    """Reconstruct provenance from pinned source, rejecting changed bundle bytes."""
    import tempfile

    bundle = Path(bundle_dir).resolve()
    envelope = json.loads((bundle / 'import.json').read_text(encoding='utf-8'))
    refs = envelope['source_refs']
    _require(refs['head'] == contract.head and refs['tree'] == contract.tree, 'source contract mismatch')
    manifest = envelope['campaign_manifest']
    with tempfile.TemporaryDirectory(prefix='qualification-validation-') as temporary:
        rebuilt = Path(temporary) / 'bundle'
        import_qualification(refs['repo'], manifest['repo'], envelope['task_id'], rebuilt,
                             run_order_seed=manifest['run_order_seed'], contract=contract)
        expected = json.loads((rebuilt / 'import.json').read_text(encoding='utf-8'))
        if manifest['contexts']:
            qualification = json.loads((rebuilt / 'private/qualification.json').read_text(encoding='utf-8'))
            _check_packet_privacy(manifest['contexts'], bundle, qualification)
            expected['campaign_manifest']['contexts'] = manifest['contexts']
            expected['campaign_manifest_digest'] = plan_digest(expected['campaign_manifest'])
            expected.update(execution_ready='YES', status='READY', missing_fields=[])
            expected['import_binding_digest'] = _binding(expected)
            validate_manifest(bundle / 'campaign-manifest.json')
        _require(envelope == expected, 'import binding or translated manifest changed')
        for path in rebuilt.rglob('*'):
            if path.is_file() and path.name not in ('import.json', 'campaign-manifest.json'):
                relative = path.relative_to(rebuilt)
                _require((bundle / relative).is_file() and path.read_bytes() == (bundle / relative).read_bytes(), f'import artifact changed: {relative}')
    _require(json.loads((bundle / 'campaign-manifest.json').read_text(encoding='utf-8')) == manifest, 'campaign document changed')
    return envelope


def attach_packets(bundle_dir: str | Path, contexts: dict[str, Any], output_dir: str | Path,
                   *, contract: SourceContract = FROZEN_SOURCE) -> dict[str, Any]:
    """Bind externally built packets into a fresh import, validating real bytes."""
    envelope = validate_import(bundle_dir, contract=contract)
    manifest = envelope['campaign_manifest']
    return import_qualification(envelope['source_refs']['repo'], manifest['repo'], envelope['task_id'],
                                output_dir, run_order_seed=manifest['run_order_seed'], contexts=contexts, contract=contract)
