# Execute the shipped path, do not build a substitute benchmark

Windows: START.cmd. Native execution and paid A/B are the operator-selected defaults.
Credentials come from .env beside START.cmd. AUTOBENCH_ALLOW_PAID is obsolete and ignored.
No Docker, WSL, administrator rights or reboot is needed. Python 3.12+ and Git must exist.
Automation: START.cmd ab --backend native --allow-local-execution --allow-live-model
Self-test only: START.cmd test --offline (NOT a coding-quality score).

Read .bench/latest.json and its summary/RESULT.md. Open referenced logs only on failure.
Do not dump .bench/, vendor/, reference_projects/, all source bundles or full CAS into context.

Runtime upgrade is automatic: acquire exact private ADCP commit, verify bytes, run its
actual regression suites plus the benchmark role/FAIL-repair-PASS integration, then activate.
Old .bench/adcp is retained in adcp-backup-* until the new runtime has passed.
The one-time qualification has a heartbeat; errors point to .bench/runtime-validation/last-gate.log.
Do not bypass the gate or silently use an old runtime with the enlarged source allocation.
Private runtime commit: 285702063815280398b95ba8696566259c8b5b34.
This is the original AA/ECACC/BADC runtime plus bounded snapshot changes, NOT an unpublished vNext gateway.

Default issue preparation accepts 16 MiB of editable Python; the explicit ADCP snapshot
allocation is 32 MiB including public helpers. An unchanged file may be up to 16 MiB,
within the aggregate source cap. Both arms retain the same full repository and hidden evaluator.
Project attempts per campaign default to 2 (or tasks_per_project, whichever is larger).
Override github.preparation_attempts_per_project in AB.toml. This is a declared sampling
quota, not a cached assertion that other commits in a repository are invalid.

Native dependencies prefer wheels but may build sdists at the requested version. The exact
resulting wheelhouse is frozen for both fresh arm environments. Windows curses is added only
when an actual pre-fix import requires it. Failed imports/tests must never become PASS or be skipped.
No new scheduler, model transport, cache service or production fake role is permitted.
User code is executed under local account permissions, not an OS sandbox. Hard CPU/RAM/dollar
and total input-token caps are not claimed. API/time/patch limits remain active.
Report actual evidence separately: host regressions, dependency experiment, private runtime gate,
real GitHub issue qualification and paid two-arm results. A pass in one does not certify another.
