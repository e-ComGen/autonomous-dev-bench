"""One pytest phase in a fresh interpreter with one explicit test-package owner."""
from pathlib import Path
import argparse
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REGRESSION_SUITES = (
    'tests/zone_development', 'tests/architecture_assurance', 'tests/harness_bridge',
    'tests/ecacc', 'tests/test_badc.py', 'tests/test_adcl.py',
)
SUPPORT_FILES = ('tests/architecture_governance/global_support.py',
                 'tests/architecture_governance/support.py')
INTEGRATION = 'tests/coding/test_runtime_upgrade.py'


def require_inputs(root, distribution):
    for relative in (*REGRESSION_SUITES, *SUPPORT_FILES):
        if not (distribution / relative).exists():
            raise ValueError('PRIVATE_GATE_INPUT_MISSING: ' + relative)
    if not (root / INTEGRATION).is_file():
        raise ValueError('BENCHMARK_GATE_INPUT_MISSING: ' + INTEGRATION)


def bind_test_package(owner):
    # Both repositories use the name tests. Resolve the REAL package/namespace
    # from this phase's owner, not pytest's synthetic parent or site-packages.
    spec = importlib.machinery.PathFinder.find_spec('tests', [str(owner)])
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError('GATE_TEST_PACKAGE_MISSING: ' + str(owner / 'tests'))
    expected = (owner / 'tests').resolve()
    if {Path(path).resolve() for path in spec.submodule_search_locations} != {expected}:
        raise RuntimeError('GATE_TEST_PACKAGE_OWNER_MISMATCH')
    if any(name == 'tests' or name.startswith('tests.') for name in sys.modules):
        raise RuntimeError('GATE_TEST_NAMESPACE_ALREADY_LOADED')
    module = importlib.util.module_from_spec(spec)
    sys.modules['tests'] = module
    if spec.loader is not None:
        spec.loader.exec_module(module)
    return expected


def run_phase(root, distribution, phase, junit):
    if phase not in {'integration', 'regressions'}:
        raise ValueError('Unknown runtime gate phase')
    root, distribution, junit = Path(root).resolve(), Path(distribution).resolve(), Path(junit).resolve()
    require_inputs(root, distribution)
    owner = root if phase == 'integration' else distribution
    paths = [distribution, distribution / 'packages/shared_contracts/src']
    if phase == 'integration':
        paths += [root / 'packages/benchmark_core', root]
    else:
        paths += [distribution / 'tests']
    sys.path[:0] = [str(path) for path in paths]
    for key in ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY',
                'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'):
        os.environ.pop(key, None)
    # Existing private tests launch subprocesses using these original source roots.
    os.environ['PYTHONPATH'] = os.pathsep.join(map(str, paths))
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['AUTOBENCH_RUNTIME_UNDER_TEST'] = str(distribution)
    namespace = bind_test_package(owner)
    print(f'Runtime gate v4: phase={phase}; tests={namespace}; pid={os.getpid()}', flush=True)
    import pytest
    selected = [str(root / INTEGRATION)] if phase == 'integration' else list(REGRESSION_SUITES)
    junit.parent.mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    try:
        os.chdir(owner)
        with tempfile.TemporaryDirectory(prefix='adcp-gate-') as temporary:
            return int(pytest.main(['-q', '--import-mode=importlib', '--maxfail=1',
                '--rootdir=' + str(owner), '--confcutdir=' + str(owner),
                '-o', 'addopts=', '-o', 'pythonpath=', '--basetemp=' + temporary,
                '--junitxml=' + str(junit), *selected]))
    finally:
        os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('distribution')
    parser.add_argument('phase', choices=('integration', 'regressions'))
    parser.add_argument('junit')
    arguments = parser.parse_args()
    return run_phase(ROOT, arguments.distribution, arguments.phase, arguments.junit)


if __name__ == '__main__':
    raise SystemExit(main())
