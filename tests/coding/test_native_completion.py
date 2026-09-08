"""Regression coverage for the operator's actual rejected source and dependency shapes."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import base64
import json
import time
import pytest
from corpus.qualification.policy import IssuePolicy
from corpus.qualification.inventory import validate_inventory
from corpus.qualification.workspace import RepositoryWorkspace
from corpus.qualification.files import code_view
from suites.coding.source import snapshot_files, write_files
from suites.coding.backends.platform_dependencies import compatibility_dependencies


def record(value):
    return {'data': base64.b64encode(value.encode()).decode(), 'executable': False}


def test_new_default_accepts_large_editable_source_without_dropping_files(tmp_path):
    files = {'core.py': 'x=1\n', 'large.py': '# ' + 'x' * 2100000 + '\n'}
    policy = IssuePolicy()
    projection = code_view({name: record(value) for name, value in files.items()}, policy.max_code_bytes)
    assert projection == files
    write_files(tmp_path, projection)
    assert snapshot_files(tmp_path) == files
    entries = [SimpleNamespace(path=name.encode(), mode=b'100644', size=len(value.encode())) for name, value in files.items()]
    assert validate_inventory(entries, policy)['code_bytes'] > 2000000
    with pytest.raises(ValueError, match='ADCP_SOURCE_VIEW_UNSUPPORTED'):
        validate_inventory(entries, replace(policy, max_code_bytes=900000))


def test_unchanged_large_asset_is_present_and_protected(tmp_path):
    files = {'core.py': record('x=1\n'), 'assets/data.jsonl': record('x' * 5186833)}
    adapter = RepositoryWorkspace(files, 262144)
    projection = {'core.py': 'x=1\n'}
    adapter.materialize(projection, tmp_path)
    assert adapter.read_candidate(projection, tmp_path) == projection
    (tmp_path / 'assets/data.jsonl').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='PROTECTED_FILE_CHANGED'):
        adapter.read_candidate(projection, tmp_path)


@pytest.mark.parametrize('code', ['import curses', 'from curses import wrapper', 'import curses as ui', 'import _curses'])
def test_windows_curses_is_an_explicit_prefixed_environment_dependency(code):
    files = {'module.py': record(code)}
    assert compatibility_dependencies(files, 'win32') == ('windows-curses==2.4.2',)
    assert compatibility_dependencies(files, 'linux') == ()


def test_comment_does_not_trigger_platform_package_install():
    assert compatibility_dependencies({'module.py': record('# import curses\nx=1\n')}, 'win32') == ()


def test_allocation_has_real_upper_bound():
    with pytest.raises(ValueError):
        IssuePolicy(max_code_bytes=33554432)
    with pytest.raises(ValueError):
        IssuePolicy(max_file_bytes=16777217)


def test_candidate_new_file_and_large_change_still_rejected(tmp_path):
    adapter = RepositoryWorkspace({'core.py': record('x=1\n')}, 1024)
    adapter.materialize({'core.py': 'x=1\n'}, tmp_path)
    (tmp_path / 'extra.py').write_text('x=2\n')
    with pytest.raises(ValueError, match='UNDECLARED_NEW_FILE'):
        adapter.read_candidate({'core.py': 'x=1\n'}, tmp_path)


def test_production_builder_never_substitutes_atomicwrites_version(tmp_path):
    from suites.coding.backends.project import build_native_project
    calls, stores = [], []
    class Provision:
        # Unit boundary only. CI additionally builds the real atomicwrites 1.4.1 sdist.
        def venv(self, directory, deadline):
            return directory / 'python'
        def execute(self, *args, **kwargs):
            return SimpleNamespace(stdout='null')
        def pip(self, python, arguments, source, deadline, **kwargs):
            arguments = tuple(map(str, arguments))
            calls.append(arguments)
            if arguments[0] == 'list':
                return SimpleNamespace(stdout=json.dumps([{'name': 'atomicwrites', 'version': '1.4.1'}]))
            if arguments[0] == 'wheel':
                wheelhouse = Path(arguments[arguments.index('--wheel-dir') + 1])
                wheelhouse.mkdir(exist_ok=True)
                (wheelhouse / 'unit-boundary.whl').write_bytes(b'unit-only wheel payload')
            return SimpleNamespace(stdout='')
    def store(*values):
        stores.append(values)
        return 'unit-environment'
    environments = SimpleNamespace(root=tmp_path, provision=Provision(), sdk_id='unit-sdk', store=store)
    files = {'pyproject.toml': record('[project]\nname="probe"\nversion="0.1"\n'),
             'requirements-test.txt': record('atomicwrites==1.4.1\n'), 'tests/test_probe.py': record('')}
    image, recipe = build_native_project(SimpleNamespace(environments=environments),
        {'base_files': files, 'base_source_digest': 'unit-source'}, IssuePolicy(), time.monotonic()+30)
    installs = [args for args in calls if args[0] == 'install' and '-r' in args]
    assert len(installs) == 1 and '--prefer-binary' in installs[0]
    assert installs[0][installs[0].index('-r') + 1] == 'requirements-test.txt'
    assert not any('--only-binary' in part or 'atomicwrites==1.4.0' in part for part in installs[0])
    directory = stores[0][1]
    assert (directory / 'source/requirements-test.txt').read_text() == 'atomicwrites==1.4.1\n'
    assert (directory / 'dependencies.txt').read_text() == 'atomicwrites==1.4.1\n'
    wheels = [args for args in calls if args[0] == 'wheel' and '-r' in args]
    assert len(wheels) == 1 and '--no-deps' in wheels[0] and '--prefer-binary' in wheels[0]
    assert Path(wheels[0][wheels[0].index('-r') + 1]) == directory / 'dependencies.txt'
