from dataclasses import replace
import sys

import pytest

from benchmark_core.cache import ActionCache
from benchmark_core.cas import CASCorruptionError, FileSystemCAS
from benchmark_core.dag import Action, CycleError, ExperimentDAG
from benchmark_core.cache import observation_action_key, oracle_action_key
from benchmark_core.environment import EnvironmentFingerprint, baseline_action_key
from benchmark_core.execution import CommandSpec


def environment(**changes):
    base = EnvironmentFingerprint(
        project_source_digest="sha256:" + "1" * 64, repository_commit="a" * 40,
        os_family="test", os_version="1", architecture="x64",
        interpreter_implementation="CPython", interpreter_version="3.11",
        interpreter_executable_digest="sha256:" + "2" * 64,
        dependency_lock_digest="sha256:" + "3" * 64,
    )
    return replace(base, **changes)


def test_cache_keys_mutate_for_every_behavioral_input():
    command = CommandSpec((sys.executable, "-c", "pass"), environment={"MODE": "one"})
    identity = {"project_digest": "sha256:" + "a" * 64, "baseline_revision": "1", "test_policy_version": "1"}
    key = baseline_action_key(environment(), command, executor_version="1", **identity)
    assert key != baseline_action_key(environment(relevant_variables=(("X", "changed"),)), command, executor_version="1", **identity)
    assert key != baseline_action_key(environment(dependency_lock_digest="sha256:" + "4" * 64), command, executor_version="1", **identity)
    assert key != baseline_action_key(environment(), replace(command, environment={"MODE": "two"}), executor_version="1", **identity)
    assert key != baseline_action_key(environment(), command, executor_version="2", **identity)
    assert key != baseline_action_key(environment(), command, project_digest="sha256:" + "b" * 64, baseline_revision="1", executor_version="1", test_policy_version="1")


def test_action_cache_separates_key_and_digest_verified_result(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas"); cache = ActionCache(tmp_path / "actions.sqlite", cas)
    key = "sha256:" + "a" * 64
    ref = cache.put_bytes(key, b"result")
    assert ref != key and cache.get_bytes(key) == b"result"
    cas.path_for(ref).write_bytes(b"corrupt")
    with pytest.raises(CASCorruptionError): cache.get_bytes(key)
    assert cache.get_ref(key) is None


def test_observation_and_oracle_keys_cover_private_and_execution_inputs() -> None:
    base = {
        "input_checkpoint_digest": "sha256:" + "1" * 64,
        "invocation": {"request": "x"}, "system_commit": "a" * 40,
        "system_configuration": {"mode": "one"}, "environment_digest": "sha256:" + "2" * 64,
        "isolation_policy": {"network": "none"}, "resource_policy": {"timeout": 10},
        "adapter_id": "adapter", "adapter_version": "1", "adapter_configuration": {"argv": ["x"]},
        "model_provider": None, "model_id": None, "prompt_version": "1", "policy_version": "1",
        "tools": (), "seed": 1, "execution_mode": "fresh_process",
    }
    key = observation_action_key(**base)
    for name, changed in (("invocation", {"request": "y"}), ("environment_digest", "sha256:" + "3" * 64),
                          ("adapter_configuration", {"argv": ["y"]}), ("seed", 2)):
        assert key != observation_action_key(**{**base, name: changed})
    oracle = {"observation_digest": "sha256:" + "4" * 64, "plan_digest": "sha256:" + "7" * 64, "oracle_id": "functional", "oracle_version": "1",
              "suite_id": "suite", "suite_version": "1", "policy_version": "1",
              "private_context_digest": "sha256:" + "5" * 64}
    oracle_key = oracle_action_key(**oracle)
    assert oracle_key != oracle_action_key(**{**oracle, "private_context_digest": "sha256:" + "6" * 64})


def test_dag_cycles_and_content_keys():
    with pytest.raises(CycleError):
        ExperimentDAG([Action("a", "x", dependencies=("b",)), Action("b", "x", dependencies=("a",))]).topological_order()
    one = ExperimentDAG([Action("a", "x", {"content": "one"})]).action_keys()["a"]
    two = ExperimentDAG([Action("a", "x", {"content": "two"})]).action_keys()["a"]
    assert one != two
