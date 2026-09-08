"""Synthetic colliding repository layouts, never private runtime or model evidence."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def put(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode('utf-8'))


def layout(directory, *, integration='pass', regression='pass', require_order=True):
    root = Path(directory) / 'benchmark with spaces'
    private = root / '.bench/.adcp-upgrade-fixture'
    events = root / 'order.txt'
    put(root, 'pyproject.toml', '[tool.pytest.ini_options]\ntestpaths=["tests"]\n')
    put(private, 'pyproject.toml', '[tool.pytest.ini_options]\ntestpaths=["tests"]\n')
    put(root, 'tests/coding/support.py', 'OWNER="benchmark"\n')
    for name in ('tools/runtime_gate.py', 'tools/runtime_gate_worker.py', 'tools/launcher_env.py'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    body = ('import pytest\npytest.skip("injected integration skip")\n' if integration == 'skip' else
            'assert False, "injected integration failure"\n' if integration == 'fail' else '')
    source = ('import os, sys\nfrom pathlib import Path\nimport pytest\nfrom .support import OWNER\n'
        '@pytest.mark.parametrize("size", [0,1], ids=["small-repair","large-repair"])\n'
        'def test_actual_cycle_large_snapshot_fail_repair_pass(size):\n'
        '    assert OWNER == "benchmark"\n'
        '    assert not os.environ.get("GITHUB_TOKEN")\n'
        '    sys.modules["phase_cache_canary"] = "integration"\n'
        + ''.join('    ' + line + '\n' for line in body.splitlines())
        + '    with Path(' + repr(str(events)) + ').open("a") as stream:\n'
        '        stream.write("integration:" + str(os.getpid()) + "\\n")\n')
    put(root, 'tests/coding/test_runtime_upgrade.py', source)
    put(private, 'tests/architecture_governance/support.py', 'OWNER="private"\n')
    put(private, 'tests/architecture_governance/global_support.py', 'from .support import OWNER\n')
    put(private, 'tests/harness_bridge/support.py', 'VALUE=7\n')
    order = ('assert Path(' + repr(str(events)) + ').read_text().count("integration:") == 2\n') if require_order else ''
    verdict = ('pytest.skip("injected regression skip")' if regression == 'skip' else
               'assert False, "injected regression failure"' if regression == 'fail' else 'assert VALUE == 7')
    put(private, 'tests/harness_bridge/test_deliberation.py',
        'from pathlib import Path\nimport os, sys, pytest\n'
        'from tests.architecture_governance.global_support import OWNER\n'
        'from .support import VALUE\n' + order +
        'def test_private_import_owner():\n'
        '    assert OWNER == "private"\n'
        '    assert "phase_cache_canary" not in sys.modules\n'
        '    ' + verdict + '\n'
        '    with Path(' + repr(str(events)) + ').open("a") as stream:\n'
        '        stream.write("regressions:" + str(os.getpid()) + "\\n")\n')
    for suite in ('zone_development', 'architecture_assurance', 'ecacc'):
        put(private, 'tests/' + suite + '/test_source.py',
            'import pytest\n@pytest.mark.parametrize("index", range(20))\n'
            'def test_source(index):\n    assert index >= 0\n')
    for suite in ('badc', 'adcl'):
        put(private, 'tests/test_' + suite + '.py', 'def test_bound():\n    assert True\n')
    return root, private, events
