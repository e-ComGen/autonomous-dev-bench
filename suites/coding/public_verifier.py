"""External host test execution followed by pure, source-bound ECACC observations."""
from types import MappingProxyType
import shared_contracts as sc
from packages import ecacc
from packages.zone_development import Role, RoleIdentity, ECACCVerifier


class PublicChecks:
    reference = ecacc.VerifierRef("benchmark.public_checks", "1")
    evidence_kind = ecacc.EvidenceKind.BEHAVIOR
    supported_obligations = (ecacc.ObligationKind.ACHIEVEMENT, ecacc.ObligationKind.PRESERVATION)

    def __init__(self, snapshot_digest=None, status=None):
        self.snapshot_digest, self.status = snapshot_digest, status

    def validate(self, definition):
        return () if definition.key in {"achievement", "preservation"} and not definition.parameters else ("Unknown public criterion",)

    def verify(self, criterion, context):
        if context.snapshot is None or context.snapshot.content_digest != self.snapshot_digest:
            return ecacc.VerifierObservation(sc.CriterionResult.INCONCLUSIVE, self.evidence_kind, (), "No matching host test observation")
        if self.status not in {"PASS", "FAIL"}:
            return ecacc.VerifierObservation(sc.CriterionResult.INCONCLUSIVE, self.evidence_kind, (), "Public test environment did not yield a verdict")
        passed = self.status == "PASS"
        return ecacc.VerifierObservation(sc.CriterionResult.PASS if passed else sc.CriterionResult.FAIL,
                                         self.evidence_kind, (ecacc.Check("public-checks-complete", passed),))


class PublicVerifier:
    identity = RoleIdentity(role=Role.VERIFIER, actor_id="benchmark-deterministic-verifier")

    def __init__(self, evaluator, checks, expected, contract):
        self.evaluator, self.checks, self.expected, self.contract = evaluator, checks, expected, contract

    def verify(self, context, run_id):
        # Execute only public tests outside the pure verifier registry. The model never
        # supplies an observation or receives hidden acceptance-test feedback.
        result = self.evaluator.score(dict(context.source.files), self.checks, self.expected)
        plugin = PublicChecks(context.source.content_digest, result["status"])
        registry = ecacc.VerifierRegistry((plugin,))
        verifier = ECACCVerifier(self.identity.actor_id, self.contract, registry)
        return verifier.verify(context, run_id)
