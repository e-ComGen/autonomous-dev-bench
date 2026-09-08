# Runtime gate adapter fix

The observed operator run stopped before activation: one benchmark integration
failed, while 495 original/private tests and 109 subtests passed. This is not a
paid A/B result. The previous installed runtime was correctly retained.

Two adapter defects were found in the exact code:
1. PublicVerifier accessed SourceSnapshot.content_digest. That serializes all
   source through ECACC's T0 canonical JSON helper, whose wire bound is 1 MiB.
   A 2 MiB source snapshot can be read successfully yet fail here before tests
   yield an ECACC observation. Bind the host test observation using the existing
   exact Git tree and exact candidate ref instead. The pure VerificationRunner
   retains its independent candidate/source/tree checks. No global wire bound,
   digest format, source file, verifier authority or acceptance rule is changed.
2. Coder attempted shared_contracts.to_wire(CandidateEvaluation) on repair.
   CandidateEvaluation is an ECACC-owned artifact, not a registered shared model.
   Use ECACC's canonical_json encoder; no truncated JSON is substituted.

PublicChecks now has verifier version 2 and compile_request uses that same
reference. Old observations cannot masquerade as the new binding version.

The automatic private runtime gate runs both small and >1 MiB FAIL/repair/PASS
integrations first, then ALL original suites. --maxfail=1 shortens failing runs;
activation still requires zero failures, errors and skips. Failure output now
prints the actual reason_code, reason and compact execution timeline.

The overlay does not edit .env, AB.toml or the private ADCP pin. Use START.cmd
normally. Do not manually edit SOURCE.json or create a QUALIFIED.json marker.
A public boundary test uses explicitly labeled test-only doubles: those results
are not proof that the full private runtime passed or a live model solved a task.
