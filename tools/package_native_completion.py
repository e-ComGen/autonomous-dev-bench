"""Package actual checked-in tested bytes; preserve operator keys/settings/runtime in overlays."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = '49a5f0844a4e2caf577d42b9c56b07bfe6651a4b'


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True).stdout


def allowed(name):
    path = Path(name)
    return not any(part in {'.git', '.github', '__pycache__', '.pytest_cache'} for part in path.parts)


def main():
    source = git('rev-parse', 'HEAD').decode().strip()
    changed = git('diff', '--name-only', BASE, 'HEAD').decode().splitlines()
    names = [name for name in git('ls-files', '-z').decode().split('\0') if name and allowed(name)]
    stage, overlay = ROOT / 'artifacts/autobenchmark', ROOT / 'artifacts/completion-fix'
    for directory in (stage, overlay):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    with zipfile.ZipFile(sys.argv[1]) as archive:
        for member in archive.infolist():
            path = Path(member.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in member.filename:
                raise ValueError('Unsafe base archive member')
            # Carry dependencies and pinned examples, not obsolete source or runtime validation claims.
            if not member.is_dir() and (member.filename.startswith('vendor/') or member.filename.startswith('.bench/seeds/')):
                target = stage / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
    for name in names:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('show', 'HEAD:' + name))
    for name in changed:
        if name in names and name not in {'AB.toml', '.env', '.env.example'}:
            target = overlay / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git('show', 'HEAD:' + name))
    evidence = {}
    acceptance = ROOT / 'artifacts/acceptance'
    for os_name in ('ubuntu-latest', 'windows-latest'):
        directory = acceptance / ('completion-' + os_name)
        tree = ET.parse(directory / 'completion-tests.xml')
        counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
        if counts['failure'] or counts['error'] or counts['testcase'] < 323:
            raise ValueError('Host suite did not pass')
        dependencies = json.loads((directory / 'dependency-upgrade.json').read_text())
        if dependencies['status'] != 'PASS' or dependencies['fresh_environments'] != 2:
            raise ValueError('Real dependency experiment missing')
        evidence[os_name] = {'host_tests': counts, 'dependency_build': dependencies}
    validation = {'source_commit': source, 'base': BASE, 'evidence': evidence,
                  'private_runtime_ci': 'NOT_CONFIRMED; local gate required before activation',
                  'paid_full_ab_executed': False, 'user_env_overwritten': False}
    for directory in (stage, overlay):
        (directory / 'NATIVE_VALIDATION.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
        shutil.copytree(acceptance, directory / 'validation-native-completion')
    files = {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(stage.rglob('*')) if path.is_file()}
    release = stage / '.bench/release.json'
    release.parent.mkdir(exist_ok=True)
    release.write_text(json.dumps({'source_commit': source, 'files': files}, indent=2), encoding='utf-8')
    print(json.dumps({'source_commit': source, 'overlay_files': len(changed), 'evidence': evidence}, indent=2))


if __name__ == '__main__':
    main()
