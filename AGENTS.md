# Run-first handoff

For a request to run or test this delivery, do not redesign or add adapters.

Windows: `START.cmd test --offline` (no arguments opens the same tests with a final pause).
Linux: `python tools/launch.py test --offline`.
Read `.bench/latest.json`, then only its named summary. Read a named log only on failure.
The packaged release contains launcher wheels and source seeds. A source-only checkout
needs one online bootstrap; omit `--offline` for that bootstrap.

## Commands

- `START.cmd doctor` checks prerequisites; no model calls.
- `START.cmd plan` freezes a deterministic **plan**, not executable task qualifications.
- `START.cmd projects --offline` checks the bundled pinned real source trees.
- `START.cmd projects --allow-network` downloads missing pinned sources.
- `START.cmd projects --allow-network --allow-local-build` also builds/runs declared baselines.
  This is explicitly local diagnostic execution of third-party code, not sandboxed scoring.
- `START.cmd discover --allow-network` collects candidates; requires read-only GITHUB_TOKEN.

A baseline PASS, a selftest PASS, or a collected issue is not coding benchmark success.
No live DSH/ADCP A/B suite or autonomous arbitrary-project builder is claimed here.
Do not invent those integrations while fulfilling a run request. Report the exact blocker.

## Minimal map

`BENCHMARK.toml`: project quotas, repetitions, limits.
`cli/oneclick/main.py`: command composition; siblings own config/report/checks/projects.
`corpus/discovery/`: evaluator-only GitHub intake.
`packages/benchmark_core/`: existing execution, cache, materialization and evidence owners.
`tests/oneclick/`, `tests/discovery/`: new regression checks.

Do not bulk-read `.bench/`, `vendor/`, reports, benchmark-info.md, or reference projects.
These are runtime data, archives or fixtures; inspect a specific file only when needed.
Never add a second runner, cache, scheduler, Zone owner or production benchmark branch.
Keep new modules <=220 lines. Production dependencies must not import this benchmark.
