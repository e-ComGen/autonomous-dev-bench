# Phase 3D7 status

The design decision inputs are now explicit and outcome-blind.

Selected pre-experiment design target:

- sensitivity scenario: `mde-15pp-conservative-discordance`;
- target power: 0.80;
- expected exact-calibration result: 37 repeats/task, 370 pairs, 740 arm runs;
- per-arm primary token cap: 262,144 total model tokens;
- per-arm request cap: 16;
- per-arm wall-time cap: 600 seconds;
- per-arm patch cap: 262,144 bytes.

This branch intentionally starts by generating a machine-validated LOCKED candidate rather than editing `PHASE3D_EXPERIMENT_PLAN.json` by hand. The canonical plan remains `DRAFT_BLOCKED` until the generated candidate, sensitivity report, pair schedule, and bound decision evidence have been inspected and committed.

No paid model call is authorized or performed by Phase 3D7 candidate generation. `PAID_PAIRED_AB` remains `NOT_RUN` and `winner` remains `UNKNOWN`.
