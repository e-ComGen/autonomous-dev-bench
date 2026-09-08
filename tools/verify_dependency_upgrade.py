"""Real native build and two fresh env imports for the observed sdist/curses failures."""
from pathlib import Path
from types import SimpleNamespace
import base64
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from suites.coding.backends.environments import NativeEnvironments
from suites.coding.backends.project import build_native_project
from suites.coding.backends.environment import private_environment
from corpus.qualification.policy import IssuePolicy
from benchmark_core.identity import Sha256Digest
from benchmark_core.execution import CommandSpec, ProcessRunner


def main():
    with tempfile.TemporaryDirectory(prefix='deps-real-') as temporary:
        root = Path(temporary)
        files = {'setup.py': 'from setuptools import setup\nsetup(name="ab_dependency_probe",version="0.0.1",py_modules=["nativeprobe"],install_requires=["atomicwrites==1.4.1"])\n',
                 'nativeprobe.py': 'import atomicwrites\nimport sys\nif sys.platform == "win32":\n    import curses\n',
                 'tests/test_probe.py': 'def test_probe():\n    import nativeprobe\n'}
        captured = {name: {'data': base64.b64encode(value.encode()).decode(), 'executable': False} for name, value in files.items()}
        runtime = SimpleNamespace(environments=NativeEnvironments(root))
        task = {'base_files': captured, 'base_source_digest': str(Sha256Digest.of(captured))}
        identity, recipe = build_native_project(runtime, task, IssuePolicy(build_seconds=600), time.monotonic() + 600)
        source, metadata = runtime.environments.load(identity)
        observations = []
        for arm in ('stock', 'cycle'):
            python = runtime.environments.execution_python(identity, root / arm, time.monotonic() + 180)
            probe = 'import nativeprobe,json,sys; from importlib.metadata import version; print(json.dumps({"atomicwrites":version("atomicwrites"),"curses":version("windows-curses") if sys.platform=="win32" else "not-required"}))'
            execution = ProcessRunner().run(CommandSpec((str(python), '-I', '-B', '-c', probe), 30,
                str(root), private_environment(root / (arm + '-home')), inherit_environment=False))
            if not execution.succeeded:
                raise RuntimeError(execution.stderr[-2000:])
            observed = json.loads(execution.stdout)
            if observed['atomicwrites'] != '1.4.1' or (sys.platform == 'win32' and observed['curses'] != '2.4.2'):
                raise ValueError('Resolved version changed')
            observations.append(observed)
        if observations[0] != observations[1]:
            raise ValueError('Fresh arm environments disagree')
        result = {'platform': sys.platform, 'status': 'PASS', 'native_builder': True,
            'real_sdist_version': '1.4.1', 'fresh_environments': 2, 'observations': observations,
            'recipe': recipe, 'wheel_hashes': metadata['wheels'], 'model_called': False}
        output = ROOT / 'artifacts/dependency-upgrade.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
