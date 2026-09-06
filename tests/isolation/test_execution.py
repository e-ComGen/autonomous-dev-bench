import sys
from pathlib import Path
import pytest

from benchmark_core.execution import CommandSpec, ExecutionResult, ProcessRunner
from benchmark_core.isolation import IsolationCapabilities, IsolationPolicy, IsolationUnavailable, NetworkPolicy, SandboxTrustStore
from benchmark_core.sandbox import DockerSandboxProvider


def test_command_spec_defensively_freezes_inputs() -> None:
    argv = [sys.executable, "--version"]
    environment = {"BENCH_VALUE": "one"}
    spec = CommandSpec(argv, environment=environment)
    argv.append("mutated")
    environment["BENCH_VALUE"] = "two"
    assert spec.argv == (sys.executable, "--version")
    assert spec.environment["BENCH_VALUE"] == "one"


def test_docker_provider_requires_immutable_image_and_attests_capabilities() -> None:
    with pytest.raises(ValueError, match="pinned"):
        DockerSandboxProvider("python:latest")
    provider = DockerSandboxProvider("python@sha256:" + "a" * 64)
    attestation = provider.attest()
    assert attestation.capabilities.network_none
    assert attestation.capabilities.filesystem_isolation
    assert not attestation.capabilities.network_allowlist
    trust_store = SandboxTrustStore({provider.provider_id: provider})
    assert trust_store.resolve(provider.provider_id, attestation.implementation_digest) is provider
    with pytest.raises(IsolationUnavailable, match="operator-pinned"):
        trust_store.resolve(provider.provider_id, "sha256:" + "0" * 64)


def test_docker_provider_builds_offline_read_only_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = DockerSandboxProvider("python@sha256:" + "a" * 64)
    temporary = tmp_path / "temporary"; temporary.mkdir()
    captured: dict[str, CommandSpec] = {}
    def fake_run(self: ProcessRunner, command: CommandSpec, *, policy: IsolationPolicy) -> ExecutionResult:
        captured["command"] = command
        return ExecutionResult(command.argv, 0, "ok", "", False, 0.1)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    result = provider.run(CommandSpec((sys.executable, "-c", "pass"), cwd=str(tmp_path), environment={"TMP": str(temporary), "TOKEN": "x", "AUTODEV_BOUND_EXECUTABLE": sys.executable, "AUTODEV_BOUND_IMPLEMENTATION": str(tmp_path)}), policy=IsolationPolicy())
    assert result.succeeded
    docker_argv = captured["command"].argv
    assert docker_argv[:5] == ("docker", "run", "--rm", "--network", "none")
    assert "--read-only" in docker_argv and provider.image in docker_argv
    assert "TOKEN=x" in docker_argv and "/opt/autodev/bin/sut-executable" in docker_argv
    build_workspace = tmp_path / "build-workspace"; build_workspace.mkdir()
    build_output = tmp_path / "build-output"
    build = provider.run(CommandSpec((sys.executable, "-m", "venv", str(build_output / "venv")), cwd=str(build_workspace),
                         environment={"AUTODEV_BUILD_OUTPUT": str(build_output)}), policy=IsolationPolicy())
    assert build.succeeded and "/environment/venv" in captured["command"].argv
    with pytest.raises(ValueError, match="network=none"):
        provider.run(CommandSpec(("python",), cwd=str(tmp_path), environment={"TMP": str(temporary)}), policy=IsolationPolicy(network=NetworkPolicy.PACKAGE_INDICES_ONLY))
    with pytest.raises(ValueError, match="existing workspace"):
        provider.run(CommandSpec(("python",), cwd=str(tmp_path / "missing"), environment={"TMP": str(temporary)}), policy=IsolationPolicy())
    with pytest.raises(ValueError, match="temporary"):
        provider.run(CommandSpec(("python",), cwd=str(tmp_path), environment={"TMP": str(tmp_path / "missing")}), policy=IsolationPolicy())


def test_plain_process_runner_refuses_authoritative_claims() -> None:
    command = CommandSpec((sys.executable, "-c", "print('unsafe')"))
    runner = ProcessRunner(capabilities=IsolationCapabilities(True, True, True, True, True))
    with pytest.raises(IsolationUnavailable, match="attested SandboxProvider"):
        runner.run(command, policy=IsolationPolicy(authoritative=True, fresh_worktree=False))
