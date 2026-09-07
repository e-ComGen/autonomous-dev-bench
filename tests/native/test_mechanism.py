from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import json
import os
import sys
import pytest
from benchmark_core.execution import CommandSpec, ProcessRunner
from suites.coding.settings import Settings
from suites.coding.backend import backend_name, create_runtime, validate_environment
from suites.coding.backends.environment import private_environment, verify_wheels, wheel_manifest
from suites.coding.backends.environments import NativeEnvironments
from tools.prepare_ab import selected_backend
from cli.oneclick.main import parser


def test_native_is_an_explicit_mechanism_not_a_new_ab_loop():
    assert backend_name(replace(Settings(), execution_backend="native")) == "native"
    assert backend_name(replace(Settings(), execution_backend="docker")) == "docker"
    assert backend_name(Settings()) == ("native" if os.name == "nt" else "docker")
    assert parser().parse_args(["ab", "--backend", "native", "--allow-local-execution"]).allow_local_execution
    assert selected_backend(["ab", "--backend=native"]) == "native"


def test_missing_local_consent_prevents_runtime_provisioning(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(ValueError, match="allow-local-execution"):
        create_runtime(tmp_path, tmp_path, replace(Settings(), execution_backend="native"))
    assert not (tmp_path / ".bench").exists()


def test_child_does_not_inherit_model_github_or_other_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-child")
    monkeypatch.setenv("GITHUB_TOKEN", "never-child")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-child")
    environment = private_environment(tmp_path / "scratch")
    result = ProcessRunner().run(CommandSpec((sys.executable, "-I", "-c",
        "import os,json;print(json.dumps({k:v for k,v in os.environ.items() if 'never-child' in v}))"),
        environment=environment, inherit_environment=False))
    assert result.succeeded and json.loads(result.stdout) == {}


def test_process_default_inheritance_is_compatible(monkeypatch):
    monkeypatch.setenv("AUTOBENCH_MARKER", "preserved")
    result = ProcessRunner().run(CommandSpec((sys.executable, "-I", "-c",
                                             "import os;print(os.environ['AUTOBENCH_MARKER'])")))
    assert result.succeeded and result.stdout.strip() == "preserved"


def test_timeout_uses_existing_runner(tmp_path):
    result = ProcessRunner().run(CommandSpec((sys.executable, "-I", "-c", "import time;time.sleep(30)"),
        0.15, environment=private_environment(tmp_path), inherit_environment=False))
    assert result.timed_out and not result.succeeded


def test_native_wheel_tamper_and_cross_backend_replay_fail(tmp_path):
    assets = NativeEnvironments(tmp_path)
    directory = assets.root / "fixture"
    wheels = directory / "wheels"
    wheels.mkdir(parents=True)
    (wheels / "fixture.whl").write_bytes(b"wheel-integrity-test-only")
    identity = assets.store("project", directory, wheel_manifest(wheels))
    assert assets.load(identity)[0] == directory
    (wheels / "fixture.whl").write_bytes(b"changed")
    with pytest.raises(ValueError, match="INTEGRITY"):
        assets.load(identity)
    with pytest.raises(ValueError, match="BACKEND"):
        assets.load("sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="BACKEND"):
        validate_environment(SimpleNamespace(), identity)


def test_configuration_rejects_unknown_backend():
    with pytest.raises(ValueError):
        replace(Settings(), execution_backend="made-up")


def test_backend_module_has_no_docker_shell_fallback():
    root = Path(__file__).resolve().parents[2]
    module = (root / "suites/coding/backends/native.py").read_text(encoding="utf-8")
    assert "DockerRuntime" not in module
    assert "os_isolation\": False" in module
    assert "cpu_memory_caps_enforced\": False" in module
