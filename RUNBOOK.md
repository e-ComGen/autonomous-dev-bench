# Random coding A/B

Extract the COMPLETE private release. Install Python 3.12+, Git and Docker Desktop
in Linux-container mode (or Docker Engine on Linux). Start Docker, then double-click
`START.cmd`. A small container image is prepared automatically on first use.
The launcher selects a random project and reconstruction task, qualifies its checks,
boots the actual DSH SDK, asks for paid-run confirmation and a hidden DeepSeek key,
then runs stock DSH and the real ADCP development cycle on identical inputs.
Keys are not written to .env, logs, source snapshots or agent containers.
The credential relay receives the key; Docker administrators remain trusted.

## Commands

`START.cmd ab --allow-live-model`: noninteractive A/B; set DEEPSEEK_API_KEY externally.
`START.cmd ab --seed 123 --allow-live-model`: repeat a recorded selection.
`START.cmd ab-preflight`: prepare/qualify and boot native SDK, no paid model call.
`START.cmd test --offline`: infrastructure self-tests, no coding score.
`START.cmd projects --offline`: verify bundled project sources.
`START.cmd discover --allow-network`: separate public GitHub candidate discovery.

A/B settings live in AB.toml: projects, tasks, repeats, full-arm time, model request
quota, per-request output cap, input request size, CPU/RAM and patch size.
Default is one task and one independent run per arm. Spend confirmation displays
request/output/time caps. They are NOT hard monetary caps; actual dollars are null.
Provider-reported token usage includes requests from every role and native retry.
An interrupted/ambiguous provider usage record stays unknown rather than becoming zero.

## Read results

`.bench/latest.json` points to one compact summary. It records seed, task, project,
exact source commit/digest, image ID, ADCP identity, order, both arm outcomes,
independent verdicts, time, request/token counts and CAS references to patches/details.
Task qualification failures occur BEFORE enrollment; model failures after enrollment
are retained. Hidden checks never feed repair. Each semantic role uses a fresh DSH home.

## Exact scope of this release

Six function-reconstruction smoke recipes use real pinned HTTPX, Requests and Pluggy
Python packages. The original source supplies a positive control; the selected function
body is removed, negative and preservation controls run, and only public examples are
made available to agents. Hidden finite probes remain with the evaluator.
This is not a mined-issue corpus, full regression suite, or evidence of large-project
coding improvement. The source view is explicitly a PYTHON_PACKAGE_PROJECTION: binary
assets and documentation are not accepted by the currently pinned ADCP snapshot format.

The cycle is the actual AA-enabled PR28 runtime at b9c933bd7727b86149da891c323a27cde5afc956.
It composes the existing ECACC verifier and BADC controller through supported role ports.
It does not claim the unpushed vNext CapabilityGateway adapter was loaded.

Agent containers have no host key, Docker socket, hidden cases or reference patch.
Their Docker network is internal; only a run-scoped relay routes completion requests
to the fixed official DeepSeek endpoint. Evaluator containers have no network.
This is finite test-based acceptance, not a proof against an actively malicious candidate.

The self-test fixture provider exists only under tests/; no fixture result is used by
`ab`. CI transport tests do not demonstrate that a paid model solves these tasks.
