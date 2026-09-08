"""External host tests followed by pure ECACC observations bound to an exact candidate."""
import shared_contracts as sc
from packages import ecacc
from packages.zone_development import Role, RoleIdentity, ECACCVerifier


class PublicChecks:
    reference = ecacc.VerifierRef("benchmark.public_checks", "2")
    evidence_kind = ecacc.EvidenceKind.BEHAVIOR
    supported_obligations = (ecacc.ObligationKind.ACHIEVEMENT, ecacc.ObligationKind.PRESERVATION)

    def __init__(self, source_tree=None, status=None, candidate_ref=None):
        self.source_tree, self.status, self.candidate_ref = source_tree, status, candidate_ref

    def validate(self, definition):
        return () if definition.key in {"achievement", "preservation"} and not definition.parameters else ("Unknown public criterion",)

    def verify(self, criterion, context):
        # A source snapshot is not a small T0 wire message. Git already supplies
        # its exact identity; do not serialize megabytes through content_digest.
        if (context.snapshot is None or self.source_tree is None or self.candidate_ref is None
                or context.candidate.as_ref() != self.candidate_ref
                or context.snapshot.git_tree() != self.source_tree):
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
        # Execute only public tests. Neither model text nor hidden acceptance
        # feedback can supply a verdict. The pure runner still verifies bindings.
        result = self.evaluator.score(dict(context.source.files), self.checks, self.expected)
        plugin = PublicChecks(context.source.git_tree(), result["status"], context.candidate.as_ref())
        registry = ecacc.VerifierRegistry((plugin,))
        verifier = ECACCVerifier(self.identity.actor_id, self.contract, registry)
        return verifier.verify(context, run_id)
