"""Actual standalone evaluator process: getuser, temporary git commits and secret scrubbing."""
from pathlib import Path
import json
import os
import sys
from benchmark_core.execution import CommandSpec, ProcessRunner
from corpus.qualification.junit import parse_junit
from suites.coding.backends.environment import private_environment

ROOT = Path(__file__).resolve().parents[2]


def test_nested_pytest_receives_service_identity_not_operator_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "operator-value-not-forwarded")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "operator-value-not-forwarded")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-not-forwarded")
    workspace = tmp_path / "workspace"
    inputs, outputs = tmp_path / "input", tmp_path / "results"
    for path in (workspace, inputs, outputs):
        path.mkdir()
    (workspace / "test_identity.py").write_text('''import getpass, os, subprocess
from pathlib import Path

def test_identity_and_temporary_commit(tmp_path):
    assert getpass.getuser() == 'autobenchmark'
    assert not any(name in os.environ for name in ('GITHUB_TOKEN','GH_TOKEN','DEEPSEEK_API_KEY'))
    subprocess.run(['git','init','--quiet',str(tmp_path)], check=True)
    (tmp_path/'value.txt').write_text('value')
    subprocess.run(['git','-C',str(tmp_path),'add','.'], check=True)
    subprocess.run(['git','-C',str(tmp_path),'commit','--quiet','-m','test commit'], check=True)
    actor = subprocess.check_output(['git','-C',str(tmp_path),'log','-1','--format=%an <%ae>']).decode().strip()
    assert actor == 'autobenchmark <autobenchmark@invalid>'
''', encoding="utf-8")
    (inputs / "checks.json").write_text(json.dumps({"paths": ["test_identity.py"], "seconds": 20}))
    environment = private_environment(tmp_path / "home", sys.executable, workspace)
    environment.update(AUTOBENCH_INPUT=str(inputs), AUTOBENCH_RESULTS=str(outputs),
                       AUTOBENCH_WORKSPACE=str(workspace), AUTOBENCH_PROJECT_PYTHON=sys.executable,
                       AUTOBENCH_SCRATCH=str(tmp_path))
    result = ProcessRunner().run(CommandSpec((sys.executable, "-I", str(ROOT / "suites/coding/pytest_process.py")),
                                30, str(workspace), environment, inherit_environment=False))
    assert result.succeeded, result.stdout + result.stderr
    assert set(parse_junit((outputs / "tests.xml").read_bytes()).values()) == {"PASS"}
    assert "operator-value-not-forwarded" not in result.stdout + result.stderr


def test_declared_plugin_source_roots_are_inside_current_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    plugin = workspace / "plugins/example/src"
    plugin.mkdir(parents=True)
    (plugin / "recipe_plugin.py").write_text("value=42\n")
    environment = private_environment(tmp_path / "home", sys.executable, workspace, ["plugins/example"])
    result = ProcessRunner().run(CommandSpec((sys.executable, "-B", "-c", "import recipe_plugin; assert recipe_plugin.value==42"),
                                20, str(workspace), environment, inherit_environment=False))
    assert result.succeeded, result.stdout + result.stderr
