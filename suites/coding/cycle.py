"""Composition of the actual ADCP AA/ECACC/BADC runtime, not an emulated loop."""
from pathlib import Path
import json
from uuid import uuid4

import shared_contracts as sc
from packages import ecacc
from packages.zone_development import RoleServices, SessionJournal, ZoneDevelopmentRuntime, ECACCVerifier
from benchmark_core.execution import ProcessRunner, CommandSpec

from .cycle_request import compile_request
from .cycle_roles import Architect, Coder, Reviewer
from .source import write_files, snapshot_files


class PublicChecks:
    reference = ecacc.VerifierRef("benchmark.public_checks", "1")
    evidence_kind = ecacc.EvidenceKind.BEHAVIOR
    supported_obligations = (ecacc.ObligationKind.ACHIEVEMENT, ecacc.ObligationKind.PRESERVATION)

    def __init__(self, evaluator, task_id, checks, expected):
        self.evaluator, self.task_id, self.checks, self.expected = evaluator, task_id, checks, expected

    def validate(self, definition):
        return () if definition.key in {"achievement", "preservation"} and not definition.parameters else ("Unknown public criterion",)

    def verify(self, criterion, context):
        result = self.evaluator.score(dict(context.snapshot.files), self.checks, self.expected)
        passed = result["status"] == "PASS"
        observations = (ecacc.Check("public-checks-complete", passed),)
        return ecacc.VerifierObservation(sc.CriterionResult.PASS if passed else sc.CriterionResult.FAIL,
                                        self.evidence_kind, observations)


def git(directory, *args):
    result = ProcessRunner().run(CommandSpec(("git", "-C", str(directory), *args), 30))
    if not result.succeeded:
        raise RuntimeError(result.stderr[-1000:])
    return result.stdout.strip()


def cycle_arm(driver, evaluator, files, recipe, public_checks, public_expected, directory, settings):
    directory = Path(directory)
    workspace = directory / "owned-workspace"
    write_files(workspace, files)
    for args in (("init", "-b", "benchmark"), ("config", "user.name", "Benchmark host"),
                 ("config", "user.email", "host@example.invalid"), ("config", "core.autocrlf", "false"),
                 ("add", "."), ("commit", "-qm", "Public benchmark input")):
        git(workspace, *args)
    repository = sc.RepositoryId(value="benchmark-projection")
    baseline = sc.SourceSnapshotRef(repository_id=repository,
        tree=sc.GitObjectId(algorithm=sc.GitObjectAlgorithm.SHA1, value=git(workspace, "rev-parse", "HEAD^{tree}")),
        commit=sc.GitObjectId(algorithm=sc.GitObjectAlgorithm.SHA1, value=git(workspace, "rev-parse", "HEAD")))
    registry = ecacc.VerifierRegistry((PublicChecks(evaluator, recipe.task_id, public_checks, public_expected),))
    session = "ab-" + uuid4().hex
    request, contract = compile_request(session, baseline, registry, settings,
        sorted(path for path in files if path.endswith(".py") and path != "public_tests.py"), recipe.description)
    roles = RoleServices(Architect(driver), Coder(driver), Reviewer(driver),
                         ECACCVerifier("benchmark-deterministic-verifier", contract, registry))
    journal = SessionJournal(directory / "cycle.sqlite3")
    runtime = ZoneDevelopmentRuntime(roles, journal)
    outcome = runtime.develop(request, workspace)
    events = journal.events(session)
    # The host's outer evaluator scores the code independently even when ADCP refuses handoff.
    candidate = snapshot_files(workspace)
    return candidate, {"status": getattr(getattr(outcome, "status", None), "value", type(outcome).__name__),
                       "runtime": type(runtime).__module__ + "." + type(runtime).__name__,
                       "internal_outcome": sc.to_wire(outcome), "invocations": driver.invocations,
                       "events": events, "verification_authority": "ECACC", "controller": "BADC"}
