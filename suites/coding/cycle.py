"""Compose the real ADCP runtime; validate its boundary before any paid episode."""
from pathlib import Path
from uuid import uuid4
import shared_contracts as sc
from packages import ecacc
from packages.zone_development import RoleServices, SessionJournal, ZoneDevelopmentRuntime, Role
from packages.zone_development.contracts import ActionRequest
from benchmark_core.execution import ProcessRunner, CommandSpec
from .cycle_request import compile_request
from .cycle_roles import Architect, Coder, Reviewer
from .source import write_files, snapshot_files
from .public_verifier import PublicChecks, PublicVerifier


def git(directory, *args):
    result = ProcessRunner().run(CommandSpec(("git", "-C", str(directory), *args), 30))
    if not result.succeeded:
        raise RuntimeError(result.stderr[-1000:])
    return result.stdout.strip()


def compose_cycle(driver, evaluator, files, recipe, public_checks, public_expected, directory, settings):
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
    registry = ecacc.VerifierRegistry((PublicChecks(),))
    session = "ab-" + uuid4().hex
    request, contract = compile_request(session, baseline, registry, settings,
        sorted(path for path in files if path.endswith(".py") and path != "public_tests.py"), recipe.description)
    roles = RoleServices(Architect(driver), Coder(driver), Reviewer(driver),
                         PublicVerifier(evaluator, public_checks, public_expected, contract))
    journal = SessionJournal(directory / "cycle.sqlite3")
    return ZoneDevelopmentRuntime(roles, journal), request, workspace, journal


def preflight_cycle(driver, evaluator, files, recipe, public_checks, public_expected, directory, settings):
    runtime, request, workspace, _ = compose_cycle(driver, evaluator, files, recipe, public_checks,
                                                   public_expected, directory, settings)
    runtime.start(request, workspace)
    step = runtime.advance(request.session_id)
    if not isinstance(step, ActionRequest) or step.actor.role is not Role.ARCHITECT:
        raise ValueError("Actual ADCP did not admit its initial architect action")
    # Merely admitting the original action is not dispatch or model execution.
    if driver.invocations:
        raise ValueError("Preflight unexpectedly dispatched a semantic role")
    return {"runtime": type(runtime).__module__ + "." + type(runtime).__name__,
            "initial_action": step.actor.role.value, "role_dispatched": False}


def cycle_arm(driver, evaluator, files, recipe, public_checks, public_expected, directory, settings):
    runtime, request, workspace, journal = compose_cycle(driver, evaluator, files, recipe, public_checks,
                                                        public_expected, directory, settings)
    outcome = runtime.develop(request, workspace)
    events = journal.events(request.session_id)
    candidate = snapshot_files(workspace)
    return candidate, {"status": getattr(getattr(outcome, "status", None), "value", type(outcome).__name__),
                       "runtime": type(runtime).__module__ + "." + type(runtime).__name__,
                       "internal_outcome": sc.to_wire(outcome), "invocations": driver.invocations,
                       "events": events, "verification_authority": "ECACC", "controller": "BADC"}
