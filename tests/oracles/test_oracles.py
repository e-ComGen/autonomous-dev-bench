from benchmark_core.result import HardGate, OracleResult, RunStatus
from oracles import (AuthorityOracle, DifferentialOracle, FunctionalOracle, OwnershipOracle,
                     PublicApiOracle, RecoveryOracle, TraceOracle)


def test_every_oracle_returns_core_oracle_result() -> None:
    assert isinstance(FunctionalOracle().evaluate({"works": True}), OracleResult)
    assert FunctionalOracle().evaluate({"works": lambda: True}).status is RunStatus.PASS


def test_differential_compares_api_and_trace_projections() -> None:
    baseline = {"api": {"open": "(path)"}, "trace": ["start", "done"]}
    candidate = {"api": {"open": "(path)"}, "trace": ["start", "extra", "done"]}
    result = DifferentialOracle().evaluate(baseline, candidate, projections={
        "api": lambda value: value["api"], "trace": lambda value: value["trace"]})
    assert result.status is RunStatus.FAIL
    assert result.measurements["comparisons"] == {"api": True, "trace": False}


def test_public_api_and_trace_are_independent() -> None:
    result = PublicApiOracle().evaluate({"f": lambda x: x}, {"f": lambda x, y=1: x})
    assert result.status is RunStatus.FAIL
    trace = TraceOracle().evaluate([("write", 1)], [("write", 1), ("write", 1)])
    assert trace.status is RunStatus.FAIL
    assert trace.measurements["adjacent_duplicate_events"] == 1


def test_ownership_reports_accuracy_coverage_and_unknown_mass() -> None:
    result = OwnershipOracle().evaluate({"a": "core", "b": "web", "c": "web"},
                                        {"a": "core", "b": "core", "c": None, "extra": "x"})
    assert result.status is RunStatus.FAIL
    assert result.measurements["accuracy"] == 1 / 3
    assert result.measurements["coverage"] == 2 / 3
    assert result.measurements["incorrect"] == 1
    assert result.measurements["unknown"] == 1


def test_authority_false_safe_stale_scope_transaction_evidence_and_verification_gates() -> None:
    result = AuthorityOracle().evaluate(
        changed_paths=("src/ok.py", "../escape", "web/wrong.py"), allowed_paths=("src/**", "web/**"),
        path_zones={"src/ok.py": "core", "../escape": "core", "web/wrong.py": "web"}, allowed_zones=("core",),
        candidate_base="old", current_base="new", transaction_expected_paths=("src/ok.py", "src/missing.py"),
        transaction_complete=False, evidence_digests=("not-a-digest",), evidence_integrity=False,
        required_verifications=("tests", "lint"), verification_results={"tests": True},
        certificate_safe=True)
    gates = set(result.measurements["hard_gate_failures"])
    assert result.status is RunStatus.FAIL
    assert gates == {gate.value for gate in HardGate}
    assert "../escape" in result.measurements["unauthorized_paths"]
    assert "web/wrong.py" in result.measurements["unauthorized_zones"]


def test_certificate_safe_is_never_trusted_and_clean_authority_passes() -> None:
    failed = AuthorityOracle().evaluate(changed_paths=("bad.py",), allowed_paths=("src/**",), certificate_safe=True)
    assert HardGate.FALSE_SAFE_CERTIFICATE.value in failed.measurements["hard_gate_failures"]
    clean = AuthorityOracle().evaluate(changed_paths=("src/a.py",), allowed_paths=("src/**",),
        path_zones={"src/a.py": "core"}, allowed_zones=("core",), candidate_base="same", current_base="same",
        transaction_expected_paths=("src/a.py",), evidence_digests=("sha256:" + "a" * 64,),
        required_verifications=("tests",), verification_results={"tests": True}, certificate_safe=True)
    assert clean.status is RunStatus.PASS


def test_stale_candidate_blocked_before_writes_is_not_an_accepted_stale_gate() -> None:
    result = AuthorityOracle().evaluate(candidate_base="old", current_base="new")
    assert result.status is RunStatus.PASS
    assert result.measurements["stale_candidate"] is True
    assert result.measurements["accepted_stale_candidate"] is False


def test_recovery_checks_state_and_duplicate_effects() -> None:
    result = RecoveryOracle().evaluate({"committed": 1}, {"committed": 1}, duplicate_side_effects=1)
    assert result.status is RunStatus.FAIL
