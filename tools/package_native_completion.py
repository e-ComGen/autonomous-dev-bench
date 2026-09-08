"""Package tested bytes as a coherent host overlay, retaining operator state."""
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
HOST_ROOTS = {'cli', 'corpus', 'faults', 'mutations', 'oracles', 'packages', 'suites', 'tools', 'tests'}
PROTECTED = {'AB.toml', 'BENCHMARK.toml', 'benchmark.lock', '.env', '.env.example'}


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True).stdout


def allowed(name):
    path = Path(name)
    return not any(part in {'.git', '.github', '__pycache__', '.pytest_cache'} for part in path.parts)


def overlay_names(names, changed):
    """An unchanged core file is still a required dependency, not an optional diff."""
    selected = set(changed)
    selected.update(name for name in names if Path(name).parts[0] in HOST_ROOTS
                    or Path(name).suffix.lower() == '.cmd')
    return sorted(name for name in set(names) & selected if allowed(name)
                  and name not in PROTECTED and Path(name).parts[0] not in {'.bench', 'vendor'})


def qualification_evidence(directory):
    historical = json.loads((directory / 'qualification-sqlfluff.json').read_text(encoding='utf-8'))
    fixture = json.loads((directory / 'recipe-environment.json').read_text(encoding='utf-8'))
    if (historical['status'] != 'PASS' or historical['model_called'] or historical['empty_patch'] != 'FAIL'
            or historical['reference_patch'] != 'PASS' or not historical['qualification']['fail_to_pass']
            or not historical['plugin_checks'] or set(historical['plugin_checks'].values()) != {'PASS'}):
        raise ValueError('Historical qualification evidence missing')
    if (fixture['status'] != 'PASS' or fixture['model_called'] or fixture['fresh_environments'] != 3
            or fixture['edited_plugin_verdict'] != 'FAIL' or len(fixture['baseline']) != 5
            or set(fixture['baseline'].values()) != {'PASS'} or fixture['baseline'] != fixture['repeated_baseline']):
        raise ValueError('Native recipe environment evidence missing')
    return {'status': 'PASS', 'repository': historical['candidate']['repository'],
            'pre_fix_commit': historical['candidate']['pre_fix_commit'],
            'reference_commit': historical['candidate']['reference_commit'],
            'acceptance_cases': historical['acceptance_cases'],
            'fail_to_pass': len(historical['qualification']['fail_to_pass']),
            'pass_to_pass': len(historical['qualification']['pass_to_pass']),
            'plugin_checks_passed': len(historical['plugin_checks']),
            'empty_patch': 'FAIL', 'reference_patch': 'PASS', 'recipe_fixture_checks': 5,
            'edited_plugin_verdict': 'FAIL', 'fresh_fixture_environments': 3,
            'model_called': False, 'scope': 'QUALIFICATION_AND_ENVIRONMENT_NOT_PAID_AB'}


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
            if not member.is_dir() and (member.filename.startswith('vendor/') or member.filename.startswith('.bench/seeds/')):
                target = stage / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
    for name in names:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('show', 'HEAD:' + name))
    included = overlay_names(names, changed)
    for name in included:
        target = overlay / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stage / name, target)
    receipt = {'schema': 'autobench.host-overlay/v1', 'source_commit': source,
               'refreshes_unchanged_host_dependencies': True,
               'preserves': sorted(PROTECTED | {'.bench/'}),
               'files': {name: hashlib.sha256((overlay / name).read_bytes()).hexdigest() for name in included}}
    for directory in (stage, overlay):
        (directory / 'OVERLAY_SOURCE.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    evidence = {}
    acceptance = ROOT / 'artifacts/acceptance'
    for os_name in ('ubuntu-latest', 'windows-latest'):
        directory = acceptance / ('completion-' + os_name)
        tree = ET.parse(directory / 'completion-tests.xml')
        counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
        if counts['failure'] or counts['error'] or counts['testcase'] < 463:
            raise ValueError('Host suite did not pass')
        dependencies = json.loads((directory / 'dependency-upgrade.json').read_text())
        if dependencies['status'] != 'PASS' or dependencies['fresh_environments'] != 2:
            raise ValueError('Real dependency experiment missing')
        gate = json.loads((directory / 'gate-process-regression.json').read_text())
        if (gate['old_exit'] == 0 or gate['new_counts'] !=
                {'testcase': 65, 'failure': 0, 'error': 0, 'skipped': 0}
                or gate['private_runtime_executed'] or gate['model_called']):
            raise ValueError('Exact gate import regression evidence missing')
        evidence[os_name] = {'host_tests': counts, 'dependency_build': dependencies,
                             'gate_import_regression': gate,
                             'qualification': qualification_evidence(acceptance / ('completion-qualification-' + os_name))}
    validation = {'source_commit': source, 'base': BASE, 'evidence': evidence,
                  'private_runtime_ci': 'NOT_CONFIRMED; local gate required before activation',
                  'paid_full_ab_executed': False, 'user_env_overwritten': False,
                  'coherent_host_overlay': True, 'overlay_files': len(included)}
    for directory in (stage, overlay):
        (directory / 'NATIVE_VALIDATION.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
        shutil.copytree(acceptance, directory / 'validation-native-completion')
    files = {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(stage.rglob('*')) if path.is_file()}
    release = stage / '.bench/release.json'
    release.parent.mkdir(exist_ok=True)
    release.write_text(json.dumps({'source_commit': source, 'files': files}, indent=2), encoding='utf-8')
    print(json.dumps(validation, indent=2))


if __name__ == '__main__':
    main()
