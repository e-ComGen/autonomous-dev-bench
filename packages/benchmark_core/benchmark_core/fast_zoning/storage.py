"""Atomic durable experiment state."""
import json
import os
from pathlib import Path
import uuid


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def state(pair_dir, status, **fields):
    path = Path(pair_dir) / 'state.json'
    prior = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    prior.update(fields, status=status)
    write_json(path, prior)
    return prior


def claim(path):
    """Exclusive durable intent; a crash never permits repeating an invocation."""
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write('claimed\n')
        stream.flush()
        os.fsync(stream.fileno())
