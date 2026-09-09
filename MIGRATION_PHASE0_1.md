# Benchmark migration Phase 0–1

This clean integration carries only the research-owned migration contract and official SWE-bench v5 grading boundary into `main`. It intentionally does **not** import the frozen legacy benchmark runtime from PR #8.

## Phase 0 — experiment contract

`ExperimentManifest` owns immutable experiment identity, task/model/agent pins, fairness budgets, execution identity and finalized trial outputs. Execution engines remain replaceable implementation details.

## Phase 1 — official grading authority

Official grading is pinned independently from Harbor:

- `swebench==5.0.2`;
- wheel SHA256 `b7f0416a1e686eca22c2f749b5f816685a202835032f6683080e2b53545bbb62`;
- `SWE-bench/swe-bench-tasks` commit `3d07b464b7b311a0cbfb5ed5b2d8a3b96f84a33d`;
- dataset `verified`;
- fixed 10-task / 10-repository parity cohort from `migration/swebench_v5_verified_parity.json`.

Accepted official parity evidence from run `34262452525`:

- empty control: 10/10 empty patches, 0 resolved, 0 infrastructure failures, 0 ambiguous failures, 0 evaluator errors;
- official gold: 10/10 resolved, 0 unresolved, 0 empty patches, 0 infrastructure failures, 0 ambiguous failures, 0 evaluator errors;
- artifact `10071398884`;
- no paid model call.

## Historical Click migration canary

The legacy qualification runtime is **not** merged into `main`. Its already accepted Click canary remains immutable historical evidence only:

- `pallets/click` issue `#2813`, PR `#2816`;
- base `1c68e531ef5e45f6facdb777c720d0f984614b81`;
- reference `4f936ac1981645488f396953bc59e50445de00b6`;
- 1 FAIL_TO_PASS / 143 PASS_TO_PASS;
- empty patch FAIL / reference patch PASS;
- accepted requalification run `34267278454`;
- no paid model call.

The standalone `swebench-v5-parity` workflow does not depend on the frozen legacy Click runtime. This prevents migration of the old custom benchmark substrate merely to preserve the historical canary.

## Boundary

Phase 1 establishes the grading authority and scientific manifest only. It does not establish model quality, does not run the paid stock-vs-ADCP experiment, and does not claim ADCP superiority.
