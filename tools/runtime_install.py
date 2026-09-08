"""Transactional pinned private-runtime upgrade. Existing state is retained until checks pass."""
from pathlib import Path
import base64
import json
import os
import shutil
import sys
import tempfile
from uuid import uuid4
from suites.coding.adcp_loading import ADCP_COMMIT, verify_distribution

REPOSITORY = "https://github.com/e-ComGen/autonomous-dev-control-plane.git"


def ensure_runtime(root, read_token, clean_environment, run_checked):
    root = Path(root)
    state = root / '.bench'
    state.mkdir(exist_ok=True)
    target = state / 'adcp'
    if state.is_symlink() or target.is_symlink():
        raise ValueError("Runtime storage must not be a symlink")
    manifest = target / 'SOURCE.json'
    if manifest.is_file():
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        if metadata.get('commit') == ADCP_COMMIT:
            verify_distribution(target)
            validate_runtime(root, target, clean_environment(), run_checked)
            return
    if not shutil.which('git'):
        raise RuntimeError('Install Git before preparing ADCP')
    print('Runtime: stage pinned large-source ADCP; existing runtime retained', flush=True)
    token = read_token()
    environment = clean_environment()
    environment['AUTOBENCH_GIT_AUTH'] = 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
    staged = state / ('.adcp-upgrade-' + uuid4().hex[:10])
    try:
        with tempfile.TemporaryDirectory(prefix='adb-source-') as temporary:
            checkout = Path(temporary)
            run_checked(['git', '-c', 'core.longpaths=true', 'init', '--quiet'], checkout, environment, 30)
            try:
                run_checked(['git', '--config-env=http.https://github.com/.extraheader=AUTOBENCH_GIT_AUTH',
                    '-c', 'credential.helper=', '-c', 'http.followRedirects=false', '-c', 'core.longpaths=true',
                    'fetch', '--quiet', '--depth=1', '--no-tags', REPOSITORY, ADCP_COMMIT], checkout, environment, 300)
            finally:
                environment.pop('AUTOBENCH_GIT_AUTH', None)
                token = None
            run_checked([sys.executable, '-B', str(root / 'tools/stage_ab_runtime.py'), str(checkout),
                         '--target', str(staged)], root, environment, 120)
        verify_distribution(staged)
        validate_runtime(root, staged, environment, run_checked)
        backup = state / ('adcp-backup-' + uuid4().hex[:10])
        if target.exists():
            os.rename(target, backup)
        try:
            os.rename(staged, target)
        except BaseException:
            if backup.exists() and not target.exists():
                os.rename(backup, target)
            raise
        print('Runtime: verified upgrade activated; previous files preserved', flush=True)
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def validate_runtime(root, distribution, environment, run_checked):
    from tools.launch import ensure_runtime as launcher_runtime
    from tools.runtime_gate import gate_identity
    marker = Path(distribution) / 'QUALIFIED.json'
    identity = gate_identity(root, distribution)
    if marker.is_file():
        previous = json.loads(marker.read_text(encoding='utf-8'))
        if previous.get('identity') == identity and previous.get('status') == 'PASS':
            return
    python = launcher_runtime(False)
    run_checked([str(python), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check',
                 'install', '--only-binary=:all:', 'pytest-subtests==0.14.2'], root, environment, 120)
    print('Runtime: actual snapshot/role/verification regression gate (no model calls)', flush=True)
    run_checked([str(python), '-B', str(Path(root) / 'tools/runtime_gate.py'), str(distribution)],
                root, environment, 900)
    if not marker.is_file() or json.loads(marker.read_text()).get('identity') != identity:
        raise RuntimeError('ADCP_RUNTIME_QUALIFICATION_MISSING')
