"""Regression coverage for the operator's actual rejected source and dependency shapes."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import base64
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


def test_production_builder_never_substitutes_atomicwrites_version():
    root = Path(__file__).resolve().parents[2]
    source = (root / 'suites/coding/backends/project.py').read_text()
    assert 'atomicwrites==1.4.0' not in source
    assert '"wheel", "--prefer-binary", "--no-deps"' in source
    assert '"install", "--prefer-binary", "-r", requirements' in source
