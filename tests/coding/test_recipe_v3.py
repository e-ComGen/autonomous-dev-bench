"""Metadata and admission regressions; no network, provider or production test substitutes."""
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import base64
import json
import time
import pytest
from corpus.qualification.files import is_test, is_pytest_module
from corpus.qualification.recipes import infer_recipe
from corpus.qualification.recipe_dependencies import dependency_groups
from corpus.qualification.tox_declarations import local_test_projects, expand_factors
from corpus.qualification.installed_extras import root_test_extra
from corpus.qualification import qualifier
from corpus.qualification.policy import IssuePolicy
from suites.coding.settings import Settings


def record(content):
    return {"data": base64.b64encode(content.encode()).decode(), "executable": False}


def base(**extra):
    return {"pyproject.toml": record('[project]\nname="probe"\nversion="0.1"\n'),
            "tests/test_real.py": record("def test_real(): assert True\n"), **extra}


@pytest.mark.parametrize("name", ["resources/test_step.png", "tests/test_data.json", "test_image.svg", "tests/conftest.py"])
def test_assets_stay_protected_but_are_not_pytest_modules(name):
    files = base(**{name: record("fixture")})
    assert is_test(name)
    assert not is_pytest_module(name)
    assert infer_recipe(files)["public_candidates"] == ["tests/test_real.py"]
    assert name in files


@pytest.mark.parametrize("name", ["test_a.py", "test/core/plugin_test.py", "pkg/tests/test_b.py"])
def test_python_test_modules_remain_eligible(name):
    assert is_pytest_module(name)
    assert name in infer_recipe(base(**{name: record("")}))["public_candidates"]


@pytest.mark.parametrize("name", ["requirements_dev.txt", "requirements_test.txt", "requirements_tests.txt", "requirements/dev.txt"])
def test_underscore_and_nested_declared_requirements_are_consumed(name):
    assert name in infer_recipe(base(**{name: record("pytest-asyncio>=1.3\n")}))["requirements"]


def test_all_declared_files_are_retained_not_arbitrary_first_two():
    files = base(**{name: record("pytest\n") for name in
        ("requirements-test.txt", "requirements-tests.txt", "requirements_dev.txt")})
    assert len(infer_recipe(files)["requirements"]) == 3


def test_groups_preserve_pins_and_expand_includes_without_taking_unrelated_groups():
    groups = {"shared_test": ["pytest==9.0.3"], "dev": [{"include-group": "shared-test"}, "pytest-asyncio>=1.3"],
              "gpu": ["deliberately-not-selected"]}
    name, dependencies = dependency_groups({"dependency-groups": groups})
    assert name == "dev" and dependencies == ["pytest==9.0.3", "pytest-asyncio>=1.3"]


@pytest.mark.parametrize("groups", [
    {"dev": [{"include-group": "missing"}]}, {"dev": [{"include-group": "dev"}]},
    {"dev": [{"include-group": "helper"}], "helper": [{"include-group": "dev"}]},
    {"dev": ["--index-url=untrusted"]}, {"dev": ["pytest\n--flag"]},
    {"dev": [{"unsupported": "pytest"}]}, {"dev": "pytest"}, {"dev": [3]},
    {"dev": [], "same_name": [], "same-name": []},
])
def test_bad_groups_cannot_turn_into_pip_flags_or_silent_missing_dependencies(groups):
    with pytest.raises(ValueError):
        dependency_groups({"dependency-groups": groups})


def plugin_files(command):
    return base(**{"tox.ini": record("[testenv]\ncommands =\n    " + command + "\n"),
                   "plugins/example/pyproject.toml": record('[project]\nname="example"\nversion="0.1"\n')})


@pytest.mark.parametrize("windows", [True, False])
def test_active_python_tox_plugin_is_selected_but_dbt_and_shell_commands_are_not(windows):
    command = ('{py,winpy}{310,311,312,313,314,}: python -m pip install "{toxinidir}/plugins/example"\n'
               '    dbt{180,190}: python -m pip install "{toxinidir}/plugins/missing-heavy-plugin"\n'
               '    python "{toxinidir}/util.py" clean-tests')
    assert local_test_projects(plugin_files(command), version=(3, 12), windows=windows) == ["plugins/example"]


@pytest.mark.parametrize("target", ["../escape", "plugins/missing", "plugins/{envname}", "plugins/example --flag"])
def test_unsafe_or_missing_selected_plugin_fails_closed(target):
    with pytest.raises(ValueError):
        local_test_projects(plugin_files('python -m pip install "{toxinidir}/' + target + '"'))


def test_factor_expansion_is_bounded():
    with pytest.raises(ValueError, match="FACTOR_LIMIT"):
        expand_factors("{a,b}" * 8)


def test_installed_metadata_not_setup_execution_resolves_dynamic_extra(tmp_path):
    message = Message()
    message["Provides-Extra"] = "testing"
    distribution = SimpleNamespace(metadata=message, read_text=lambda name: json.dumps(
        {"url": tmp_path.as_uri(), "dir_info": {"editable": True}}))
    assert root_test_extra(tmp_path, [distribution]) == "testing"
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        root_test_extra(tmp_path, [distribution, distribution])
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        root_test_extra(tmp_path / "other", [distribution])


def capture():
    return {"candidate": {"repository": "example/probe", "issues": [{"title": "Fix value", "body": "Return one"}]},
            "identity": "sha256:" + "1" * 64, "projection": {"core.py": "value=0\n"},
            "fix_code": {"core.py": record("value=1\n")}, "base_source_digest": "sha256:" + "2" * 64,
            "test_overlay": {"tests/test_fix.py": record("test"), "tests/test_fixture.png": record("asset")},
            "base_files": {"core.py": record("value=0\n")}}


def test_bad_public_baseline_stops_before_eight_repeated_environments(tmp_path, monkeypatch):
    calls = []
    class Evaluator:
        def __init__(self, *args):
            pass
        def observe(self, projection, check):
            calls.append(check)
            return {"public::test": "FAIL"}
    monkeypatch.setattr(qualifier, "PytestEvaluator", Evaluator)
    monkeypatch.setattr(qualifier, "build_project_image", lambda *args: ("image", {"public_candidates": ["tests/test_public.py"]}))
    with pytest.raises(ValueError, match="PUBLIC_BASELINE_NOT_GREEN"):
        qualifier.qualify(tmp_path, SimpleNamespace(scratch=tmp_path), capture(), IssuePolicy(), Settings(), 7, time.monotonic()+30)
    assert len(calls) == 1 and calls[0]["kind"] == "public"


def test_asset_only_reference_is_rejected_before_build(tmp_path, monkeypatch):
    value = capture()
    value["test_overlay"].pop("tests/test_fix.py")
    monkeypatch.setattr(qualifier, "build_project_image", lambda *args: pytest.fail("Must not build"))
    with pytest.raises(ValueError, match="ACCEPTANCE_TEST_MODULES_MISSING"):
        qualifier.qualify(tmp_path, None, value, IssuePolicy(), Settings(), 7, time.monotonic()+30)
