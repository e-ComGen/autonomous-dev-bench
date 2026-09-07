# Automatic real-issue A/B

Extract the whole release. Install Python 3.12+, Git and Docker Desktop in Linux-container mode
(or Docker Engine on Linux), start Docker, and double-click START.cmd.

The launcher asks for a read-only GitHub token when absent. It automatically downloads the
pinned private ADCP runtime, builds the native DSH image, searches public Python repositories,
finds real issues with merged fixes, obtains exact before/after trees, derives an environment
recipe, and repeatedly verifies bug reproduction and regression preservation.
It rejects unsupported candidates within AB.toml preparation/API budgets and selects the
requested random qualified tasks. It then asks for paid-run confirmation and a hidden DeepSeek
key, runs both systems independently, and evaluates both resulting patches with protected tests.
No manual repository path, issue selection, shell recipe, task generation or source editing is
required. No reconstruction recipe is used as a fallback.

## Commands

- START.cmd: interactive automatic A/B.
- START.cmd ab --allow-live-model: automation with keys already in environment.
- START.cmd ab-preflight: acquisition, qualification, private runtime load and actual DSH boot; no paid prompt.
- START.cmd qualify: acquisition/build/qualification only; no private ADCP or model required.
- START.cmd test --offline: infrastructure self-tests only.
- START.cmd ab --replay .bench/runs/<run>/selection.json --allow-live-model: exact retained task/image replay.

AB.toml controls tasks, repeats, per-arm time/requests/output cap, RAM/CPU and patch bytes.
Its [github] section controls search pool, age, stars, candidate/project limits, preparation
and build time, public regression scope and required counts of distinct small/medium/large
qualified projects. Size is measured in editable Python lines, not stars or download size.
Quotas never silently substitute small projects for large ones. The bounded search is not a
uniform sample of every GitHub repository. Exhaustion gives a reasoned incomplete result.

## Result

.bench/latest.json points to a compact summary and adjacent RESULT.md. Exact task metadata,
base/fix commits, source/image/config identities, locked selection, both outcomes, request/token
accounting, timing, patches, failures and diagnostic evidence are retained in the existing CAS.
Large row sets and logs are referenced, not printed. Do not feed full CAS contents to Codex.
A seed repeats sampling logic; exact replay requires selection.json, its CAS records and image IDs.

## Supported scope and limitations

This release supports automatically buildable Python/pytest projects with a linked historical
issue, an unambiguous supported Git history, changes to existing Python modules and separable
regression tests. Config migrations, new/deleted production modules, binary/symlink worktrees,
external services, unsupported test frameworks and large ADCP code views are rejected.
Baseline public checks are a recorded bounded sample, not necessarily the project's full suite.
Qualification is executable evidence, not proof that tests completely capture human intent.
Historical public issues may have been in model training; no contamination-free claim is made.

The full pre-fix repository is materialized in native agent/evaluator containers. For the actual
legacy ADCP contract, all editable Python files form a bounded source view; non-code artifacts
are present but protected. Both arms have the same common source/editing restrictions.
B uses the actual PR28 AA/ECACC/BADC runtime, NOT an emulated loop and NOT the separate unpushed
vNext adapter. Its exact private source is validated before loading and never distributed publicly.

Agent networks are internal and credentials stay in a dedicated relay outside their containers.
The relay routes only to the fixed official DeepSeek completion endpoint. Hidden test data and
reference changes are never mounted in agents. Evaluators have no network. Project build scripts
run inside disposable Docker build containers without user credentials. Docker administrators
and the local operator are trusted; this is not a proof against malicious kernels/test evasion.
Model request and per-request output caps include all native retries and cycle roles. Whole-arm
work uses a shared deadline; container cleanup may add overhead. Costs remain unpriced/null:
there is no claim of a guaranteed dollar cap. Unknown usage is never counted as free.
