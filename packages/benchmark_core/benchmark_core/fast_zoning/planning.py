"""Versioned read-only plan validation. Routing identity belongs to the host."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PLAN_FIELDS = frozenset(('likely_reads', 'likely_writes', 'diagnosis', 'changes', 'tests', 'evidence'))
MAX_REPLY_BYTES = 65536


class PlanValidationError(ValueError):
    """Stable failure codes; never reinterpret malformed output as success."""


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PlanValidationError('PLAN_DUPLICATE_FIELD')
        value[key] = item
    return value


def _reject_constant(_value):
    raise PlanValidationError('PLAN_NONFINITE_VALUE')


def _path(value, root):
    if (type(value) is not str or not value or len(value) > 1024
            or '\\' in value or ':' in value or any(ord(c) < 32 for c in value)):
        raise PlanValidationError('PLAN_PATH_INVALID')
    parts = value.split('/')
    if any(p in ('', '.', '..') or p.casefold() in ('.git', '.autozoning')
           or p.endswith((' ', '.')) for p in parts):
        raise PlanValidationError('PLAN_PATH_INVALID')
    local = root.joinpath(*parts)
    try:
        current = local
        while current != root:
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise PlanValidationError('PLAN_PATH_INDIRECT')
            current = current.parent
        if not local.is_file() or not local.resolve(strict=True).is_relative_to(root):
            raise PlanValidationError('PLAN_PATH_UNAVAILABLE')
    except OSError as error:
        raise PlanValidationError('PLAN_PATH_UNAVAILABLE') from error
    return local


def parse_plan_reply(raw: str, *, task_id: str, workspace: Path,
                     logical_task_id: str | None = None) -> dict:
    """Accept only a whole JSON object (optionally fenced); never repair JSON."""
    if type(task_id) is not str or not task_id.strip():
        raise ValueError('host task_id is required')
    if logical_task_id is not None and (type(logical_task_id) is not str or not logical_task_id.strip()):
        raise ValueError('invalid host logical_task_id')
    if type(raw) is not str or len(raw.encode('utf-8')) > MAX_REPLY_BYTES:
        raise PlanValidationError('PLAN_REPLY_SIZE')
    text = raw.strip()
    lines = text.splitlines()
    fenced = len(lines) >= 3 and lines[0] in ('```', '```json') and lines[-1] == '```'
    if fenced:
        text = '\n'.join(lines[1:-1])
    try:
        value = json.loads(text, object_pairs_hook=_unique, parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise PlanValidationError('PLAN_JSON_INVALID') from error
    if type(value) is not dict or set(value) != PLAN_FIELDS:
        raise PlanValidationError('PLAN_FIELDS_INVALID')
    if type(value['diagnosis']) is not str or not value['diagnosis'].strip():
        raise PlanValidationError('PLAN_DIAGNOSIS_REQUIRED')
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('workspace must be a directory')
    for key in ('likely_reads', 'likely_writes', 'changes', 'tests', 'evidence'):
        if type(value[key]) is not list or len(value[key]) > 256:
            raise PlanValidationError('PLAN_LIST_INVALID')
    for key in ('likely_reads', 'likely_writes'):
        for path in value[key]:
            _path(path, root)
        if len({p.casefold() for p in value[key]}) != len(value[key]):
            raise PlanValidationError('PLAN_DUPLICATE_PATH')
    if not value['likely_writes']:
        raise PlanValidationError('PLAN_WRITE_SCOPE_REQUIRED')
    for key in ('changes', 'tests'):
        if not value[key] or any(type(s) is not str or not s.strip() for s in value[key]):
            raise PlanValidationError('PLAN_TEXT_LIST_INVALID')
    if not value['evidence']:
        raise PlanValidationError('PLAN_EVIDENCE_REQUIRED')
    for item in value['evidence']:
        if (type(item) is not dict or not {'path', 'line'} <= set(item)
                or set(item) - {'path', 'line', 'snippet'}):
            raise PlanValidationError('PLAN_EVIDENCE_INVALID')
        path = _path(item['path'], root)
        if type(item['line']) is not int or not 1 <= item['line'] <= len(path.read_bytes().splitlines()):
            raise PlanValidationError('PLAN_EVIDENCE_LINE_INVALID')
        if 'snippet' in item and type(item['snippet']) is not str:
            raise PlanValidationError('PLAN_EVIDENCE_INVALID')
    return {'schema': 'planning-ab-result/2', 'task_id': task_id,
            'logical_task_id': logical_task_id, 'plan': value,
            'wire_format': 'FENCED_JSON' if fenced else 'JSON',
            'raw_reply_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'write_authorized': False}


def planning_instruction(task_text: str) -> str:
    return ('Planning only: inspect repository sources, without editing, command execution or network access. '
            'Return one JSON object with exactly these six fields: likely_reads (file paths), '
            'likely_writes (nonempty file paths), diagnosis (text), changes (nonempty text array), '
            'tests (nonempty text array), evidence (nonempty array of {path,line} with 1-based lines). '
            'Do not include schema, task_id or logical_task_id: the host binds these separately. '
            'Follow the declared tool argument schemas. Stop once the defect and minimal change are identified. '
            'Do not invent missing evidence. This plan grants no write permission.\n\n' + task_text)
