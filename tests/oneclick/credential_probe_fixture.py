"""Temporary host-handoff fixture. Only private acquisition and final CLI dispatch are test probes."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
KEYS = ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OTHER_SECRET')
GITHUB = 'unit-only-host-github'
PROVIDER = 'unit-only-host-provider'
FILES = (
    'START.cmd', 'AB.toml', 'tools/bench.py', 'tools/launch.py', 'tools/start_ready.py',
    'tools/launcher_env.py', 'tools/launcher_credentials.py', 'tools/launcher_lock.py',
    'tools/requirements-launcher.txt', 'suites/coding/settings.py', 'suites/coding/spend.py',
    'suites/coding/backends/environment.py', 'corpus/qualification/policy.py', 'corpus/discovery/github.py',
)


def populate(root, source=ROOT, *, wheels=False):
    root, source = Path(root), Path(source)
    root.mkdir(parents=True, exist_ok=True)
    for relative in FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    shutil.copytree(source / 'packages/benchmark_core', root / 'packages/benchmark_core',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    for directory in ('cli/oneclick', 'tools', 'suites/coding/backends', 'corpus/qualification', 'corpus/discovery'):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        while path != root:
            (path / '__init__.py').touch()
            path = path.parent
    shutil.copyfile(source / 'tests/oneclick/credential_probe_cli.py', root / 'cli/oneclick/main.py')
    (root / 'tools/prepare_ab.py').write_text(
        '"""TEST ONLY private boundary; no qualification or activation claim."""\n'
        'from pathlib import Path\ndef prepare_runtime():\n'
        '    Path("private-boundary.txt").write_text("TEST_ONLY_NO_PRIVATE_EXECUTION")\n', encoding='utf-8')
    if wheels:
        shutil.copytree(source / 'vendor/wheels', root / 'vendor/wheels')
    return root


def clean_parent():
    values = {key: value for key, value in os.environ.items()
              if key not in {*KEYS, 'AUTOBENCH_RUNTIME_UNDER_TEST', 'AUTOBENCH_ALLOW_PAID'}}
    values.update(OPENAI_API_KEY='unit-only-unrelated', OTHER_SECRET='unit-only-unrelated')
    return values


def credentials(root, source='dotenv'):
    values = clean_parent()
    key = 'GH_TOKEN' if source.endswith('alias') else 'GITHUB_TOKEN'
    if source.startswith('dotenv'):
        (root / '.env').write_text(key + '=' + GITHUB + '\nDEEPSEEK_API_KEY=' + PROVIDER + '\n', encoding='utf-8')
    else:
        (root / '.env').write_text('# Test process environment supplies credentials.\n', encoding='utf-8')
        values.update({key: GITHUB, 'DEEPSEEK_API_KEY': PROVIDER})
    return values


def invoke(root, arguments, environment, *, full_chain=False):
    if full_chain and os.name == 'nt':
        argv = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'START.cmd', *arguments]
    else:
        script = 'tools/start_ready.py' if full_chain else 'tools/bench.py'
        argv = [sys.executable, '-I', '-B', script, *arguments]
    path = root / 'observed.json'
    path.unlink(missing_ok=True)
    result = subprocess.run(argv, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=600 if full_chain else 30, shell=False)
    output = result.stdout + result.stderr
    if result.returncode:
        raise AssertionError('TEST_ENTRYPOINT_FAILED: ' + output[-2000:])
    observed = json.loads(path.read_text(encoding='utf-8'))
    for sentinel in (GITHUB, PROVIDER, 'unit-only-unrelated'):
        if sentinel in output or sentinel in path.read_text(encoding='utf-8'):
            raise AssertionError('TEST_CREDENTIAL_DISCLOSURE')
    return observed
