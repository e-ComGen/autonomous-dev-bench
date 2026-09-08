"""Apply the shipped overlay to an older mixed install; no private runtime or API calls."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CORE = 'packages/benchmark_core/benchmark_core/execution.py'


def unpack(archive_path, destination):
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename
                    or ':' in member.filename or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('Unsafe base archive member')
            if not member.is_dir():
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))


def probe(checkout, expected):
    script = ('from pathlib import Path; import sys; '
              'root=Path.cwd(); sys.path[:0]=[str(root),str(root/"packages/benchmark_core")]; '
              'from benchmark_core.execution import ProcessRunner; '
              'assert callable(getattr(ProcessRunner(),"cancel_running",None)) is ' + repr(expected))
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script], cwd=checkout,
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError('Host API probe failed: ' + result.stderr[-2000:])


def main():
    overlay = ROOT / 'artifacts/completion-fix'
    metadata = json.loads((overlay / 'OVERLAY_SOURCE.json').read_text(encoding='utf-8'))
    if CORE not in metadata['files']:
        raise ValueError('Overlay omits the unchanged process owner')
    evidence = ROOT / 'artifacts/release-evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='older install with spaces ') as temporary:
        checkout = Path(temporary) / 'autobenchmark'
        checkout.mkdir()
        unpack(Path(sys.argv[1]), checkout)
        original = (checkout / CORE).read_text(encoding='utf-8')
        if 'def cancel_running(self):' not in original:
            raise ValueError('Unexpected baseline; cannot inject the declared ABI regression')
        # Deliberately reproduce the observed API shape in an isolated test install.
        (checkout / CORE).write_text(original.replace('def cancel_running(self):',
                                    'def removed_cleanup(self):', 1), encoding='utf-8')
        probe(checkout, False)
        retained = {}
        for name in ('AB.toml', 'BENCHMARK.toml', 'benchmark.lock'):
            retained[name] = (checkout / name).read_bytes()
        retained.update({'.env': b'GITHUB_TOKEN=overlay-test-only\nDEEPSEEK_API_KEY=overlay-test-only\n',
                         '.bench/adcp/SOURCE.json': b'{"commit":"preserved-operator-runtime"}',
                         '.bench/cas/operator-sentinel': b'preserved historical CAS bytes',
                         '.bench/runs/operator-sentinel.json': b'{"historical":true}'})
        for name, content in retained.items():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for path in overlay.rglob('*'):
            if path.is_file():
                name = path.relative_to(overlay)
                if name.as_posix() in retained or name.parts[0] == '.bench':
                    raise ValueError('Overlay tries to overwrite operator state: ' + str(name))
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for name, expected in metadata['files'].items():
            if hashlib.sha256((checkout / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Overlay payload differs after installation: ' + name)
        probe(checkout, True)
        if (checkout / '.git').exists():
            raise ValueError('Overlay test must not depend on a developer checkout')
        argv = ([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'START.cmd', 'test', '--offline']
                if os.name == 'nt' else [sys.executable, '-I', 'tools/launch.py', 'test', '--offline'])
        environment = {key: value for key, value in os.environ.items() if key not in
                       {'GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'AUTOBENCH_RUNTIME_UNDER_TEST'}}
        result = subprocess.run(argv, cwd=checkout, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
        (evidence / 'overlay-test.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            print(result.stdout[-8000:] + result.stderr[-4000:], file=sys.stderr)
            raise RuntimeError('Installed overlay self-test failed')
        pointer = json.loads((checkout / '.bench/latest.json').read_text(encoding='utf-8'))
        summary_path = (checkout / pointer['report']).resolve()
        if not summary_path.is_relative_to((checkout / '.bench/runs').resolve()):
            raise ValueError('Unexpected report location')
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if summary['status'] != 'CHECKED' or summary.get('live_model_called'):
            raise ValueError('Overlay did not finish the non-billable self-test')
        for name, content in retained.items():
            if (checkout / name).read_bytes() != content:
                raise ValueError('Operator input was changed: ' + name)
        for name, expected in metadata['files'].items():
            if hashlib.sha256((checkout / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Self-test modified shipped source: ' + name)
    report = {'status': 'PASS', 'source_commit': metadata['source_commit'], 'platform': sys.platform,
              'scope': 'REAL_OVERLAY_ON_OLDER_RELEASE_WITH_INJECTED_STALE_HOST_API',
              'api_absent_before_overlay': True, 'api_present_after_overlay': True,
              'shipped_payload_hashes_verified': len(metadata['files']),
              'operator_state_preserved': sorted(retained), 'path_with_spaces': True,
              'git_checkout_required': False, 'installed_selftest': 'CHECKED',
              'private_runtime_executed': False, 'model_called': False}
    (evidence / 'overlay-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Include the install-specific receipt without changing the complete release hash inventory.
    (overlay / 'OVERLAY_VALIDATION.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
