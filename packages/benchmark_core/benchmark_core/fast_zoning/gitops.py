"""Disposable independent Git copies and complete candidate evidence."""
import os
from pathlib import Path
import subprocess
import tempfile


def git(repo, *args, env=None):
    return subprocess.run(['git', '-C', str(repo), *map(str, args)], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=120).stdout


def verify_source(repo, head, tree):
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != head:
        raise ValueError('source HEAD mismatch')
    if git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip() != tree:
        raise ValueError('source TREE mismatch')
    if git(repo, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('dirty source')


def clone_snapshot(repo, destination, head, tree):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('fresh destination already exists')
    subprocess.run(['git', 'clone', '--no-local', '--no-hardlinks', '--no-checkout',
                    str(repo), str(destination)], check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, timeout=120)
    git(destination, '-c', 'core.autocrlf=false', 'checkout', '--detach', head)
    verify_source(destination, head, tree)
    return destination


def capture_patch(workspace, base_head, output):
    """A private index includes ignored/untracked files without changing user index."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='campaign-index-') as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git(workspace, 'read-tree', base_head, env=env)
        git(workspace, 'add', '--all', '--force', '--', '.', env=env)
        patch = git(workspace, 'diff', '--cached', '--binary', '--full-index',
                    '--find-renames', base_head, '--', env=env)
        raw = git(workspace, 'diff', '--cached', '--name-status', '-z',
                  '--find-renames', base_head, '--', env=env).decode('utf-8', 'surrogateescape').split('\0')
        changes = []
        while raw and raw[0]:
            status, name = raw.pop(0), raw.pop(0)
            entry = {'status': status, 'path': name}
            if status.startswith(('R', 'C')):
                entry['old_path'] = name
                entry['path'] = raw.pop(0)
            changes.append(entry)
        numstat = git(workspace, 'diff', '--cached', '--numstat', '-z', base_head,
                      '--', env=env).decode('utf-8', 'surrogateescape')
    (output / 'patch.diff').write_bytes(patch)
    return {'patch_size': len(patch), 'changed_files': [row['path'] for row in changes],
            'changes': changes, 'numstat': numstat, 'patch_produced': bool(changes)}


def apply_patch(workspace, patch):
    if Path(patch).stat().st_size:
        git(workspace, 'apply', '--binary', '--index', str(Path(patch).resolve()))
