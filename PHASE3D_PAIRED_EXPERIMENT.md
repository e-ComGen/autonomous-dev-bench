# Phase 3D — paired causal experiment controller

Phase 3D owns the experiment-level relationship between the two atomic coding trials used by the first causal Stock-vs-ADCP comparison. Phase 3D2 adds an outcome-blind preregistration layer that the paid controller must satisfy before either arm executes.

It does **not** run the paid comparison and does not establish a winner.

## Scientific unit

The pair is:

```text
same SWE-bench task
same DeepSeek model
same provider route
same primary model-token budget
same Harbor execution policy
same repeat index
same derived seed

Arm A: stock DeepSeek Harness
Arm B: pinned ADCP orchestration
```

The agent implementation is the intended treatment difference.

`ExperimentManifest` remains the immutable identity of one atomic arm. `PairedExperimentPlan` owns the relationship between the two arms and materializes one manifest for Stock and one for ADCP.

## Fairness enforcement

`require_causal_pair(...)` rejects a pair if the arm manifests differ in any of:

- task identity;
- model identity / decoding;
- budget;
- execution substrate / resource policy;
- repeat index;
- seed.

The two agent manifests must be distinct. Pre-execution manifests may not already contain outputs.

The execution order is committed before either arm runs. `sha256-parity-v1` derives Stock-first vs ADCP-first deterministically from the pair id, task id, repeat index and seed. The algorithm is part of pair identity, so changing the ordering rule creates a different pair.

## Phase 3D2 preregistration

`PHASE3D_EXPERIMENT_PLAN.json` is the outcome-blind design source for the first paid experiment. `ExperimentDesignSnapshot.from_repository(...)` validates it against accepted repository locks rather than trusting duplicated identifiers in the plan.

The plan fixes:

- the exact 10-task SWE-bench Verified cohort accepted in Phase 1;
- official SWE-bench 5.0.2 and the exact task-repository commit;
- Stock DeepSeek Harness commit `a66e4702047846cdaa10c66c9d3df3951f5ea70d`;
- ADCP commit `285702063815280398b95ba8696566259c8b5b34`, exact runtime and integration identity;
- model `deepseek-v4-flash` and provider route `deepseek-official`;
- Harbor 0.22.0 at `d4509bbd3804f4b408527f476d764dacd988791d`;
- official SWE-bench v5 as final grading authority;
- primary endpoint `official_swebench_v5_resolved`;
- primary estimand `paired_difference_in_resolution_rate_adcp_minus_stock`;
- paired reporting, discordant-pair reporting and the prohibition on a synthetic universal weighted score;
- fixed-pair stopping with no interim outcome-based stopping;
- allowed infrastructure/accounting exclusions and an explicit prohibition on excluding a pair because it hurts the hypothesis;
- fresh independent environments per arm and no cross-arm mutable-state reuse.

The plan also precommits identity derivation:

```text
master_seed = 20260909
pair_seed_algorithm = sha256-master-task-repeat-v1
pair_id_template = phase3d-{task_id}-r{repeat_index}
pair_order_algorithm = sha256-parity-v1
```

Changing the cohort, treatment commits, model/provider, Harbor identity, grading authority, endpoint/estimand, exclusion policy or stopping semantics is a hard `ExperimentPlanInvalid`, not a soft readiness blocker.

## Deliberately unset design choices

The repository does not invent cost/sample-size-sensitive values merely to reach `paid_ready`. The current design remains `DRAFT_BLOCKED` because these values have not yet been precommitted:

```text
EXPERIMENT_PLAN_NOT_LOCKED
REPEAT_COUNT_NOT_PRECOMMITTED
PRIMARY_TOKEN_BUDGET_NOT_PRECOMMITTED
SECONDARY_RESOURCE_LIMITS_NOT_PRECOMMITTED
```

Once repeat count is selected, `required_completed_pairs` must equal `task_count * repeat_count`; otherwise the plan is invalid. The primary fairness measure remains total model tokens. Input/output caps, request cap, wall-time cap and patch-byte cap are secondary hard resource limits and must also be fixed before the design can be locked.

## Runtime binding to the locked design

Paid admission does not stop at validating the JSON file. A concrete `PairedExperimentPlan` must match the locked `ExperimentDesignSnapshot` before either executor runs.

The runtime pair is checked for:

- task membership in the preregistered cohort;
- exact pair id derived from task/repeat;
- exact seed derived from master seed/task/repeat;
- pair-order algorithm;
- task-repository commit and official evaluator version;
- Stock and ADCP implementation + commit identities;
- model/provider identity;
- all six budget/resource caps;
- Harbor version and Docker provider.

Canonical `CommitPin` values are compared by their exact textual SHA, so representation differences cannot create false mismatches or weaken pinning.

## Receipt binding

Every arm executor must return an `ArmExecutionReceipt` that names its arm and binds the exact planned atomic `ExperimentManifest.identity`.

A receipt for the wrong arm or a different manifest is rejected. The final `PairedRunReceipt` binds:

- pair identity;
- committed execution order;
- paid/dry-run mode;
- paid admission identity when applicable;
- exactly one Stock receipt;
- exactly one ADCP receipt.

## Paid admission

`PaidAdmissionSnapshot.from_repository(...)` content-binds:

- `PHASE3D_EXPERIMENT_PLAN.json`;
- `migration/swebench_v5_verified_parity.json`;
- `HARBOR.lock.json`;
- `DEEPSEEK_V4_ESTIMATOR.lock.json`;
- `ADCP.lock.json`;
- `DEEPSEEK_HARNESS.lock.json`.

The current repository intentionally remains blocked by both design and external qualification gates:

```text
EXPERIMENT_PLAN_NOT_LOCKED
REPEAT_COUNT_NOT_PRECOMMITTED
PRIMARY_TOKEN_BUDGET_NOT_PRECOMMITTED
SECONDARY_RESOURCE_LIMITS_NOT_PRECOMMITTED
DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS
DEEPSEEK_ESTIMATOR_NOT_PAID_READY
ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS
ADCP_NOT_PAID_READY
```

When `paid=True`, `PairedExperimentController` validates this admission snapshot and then the concrete runtime pair **before invoking either arm executor**. A blocked or design-drifting paid run therefore cannot make a Stock call first and discover the problem afterward.

`tools/phase3d_paid_preflight.py` exposes the same check as machine-readable JSON. It reports the design status/blockers plus SHA256 identities for the experiment plan, cohort, Harbor, estimator, ADCP and Stock locks. It makes no model call.

## Dry-run boundary

Dry-run mode exists to qualify experiment orchestration without spending model tokens. If either executor reports `model_called=true`, the controller rejects the run with `DryRunModelCallForbidden`.

Dry-run PASS is evidence about pair orchestration only. It cannot be promoted to a paid result.

## Accepted qualifications

Phase 3D controller foundation:

- CI run `34357064416` on head `00b734b816262b4525518baea4314fdb9be6bc2b` — PASS;
- firewall PASS;
- Ubuntu Python 3.11 / 3.12 / 3.13 pytest + build PASS;
- Windows Python 3.11 / 3.12 / 3.13 pytest + build PASS;
- no model/provider call.

Phase 3D2 preregistration implementation:

- initial CI exposed a canonical `CommitPin` vs string comparison bug in the new runtime-design binding;
- the gate itself correctly rejected the mismatched representation;
- the comparison was fixed to exact canonical textual commit pins without relaxing identity checks;
- CI run `34360073928` on head `79d0a8256d02092cfdc3eeea221500efa790a3d0` — PASS;
- firewall PASS;
- Ubuntu Python 3.11 / 3.12 / 3.13 pytest + build PASS;
- Windows Python 3.11 / 3.12 / 3.13 pytest + build PASS;
- no model/provider call.

Machine-readable state is recorded in `PHASE3D.lock.json` and `PHASE3D_EXPERIMENT_PLAN.json`.

## Current state

```text
PHASE3A_MODEL_BUDGET_AUTHORITY: PASS
PHASE3B_CROSS_PROCESS_PROXY: PASS
PHASE3B_V4_OFFLINE_EXACT_ESTIMATOR: PASS
PHASE3B_LIVE_PARITY_CAPTURE_CODE: PASS
PHASE3B_LIVE_PROVIDER_PROMPT_PARITY: NOT_RUN
PHASE3C1_PUBLIC_ADCP_HARBOR_BOUNDARY: PASS
PHASE3C2_PRIVATE_QUALIFIER_CODE: PASS
PHASE3C2_PINNED_PRIVATE_RUNTIME_EXECUTION: NOT_RUN
PHASE3D_PAIRED_CONTROLLER: PASS
PHASE3D2_PREREGISTRATION_IMPLEMENTATION: PASS
PHASE3D2_EXPERIMENT_DESIGN: DRAFT_BLOCKED
PHASE3D_PAID_ADMISSION: BLOCKED
PAID_PAIRED_AB: NOT_RUN
WINNER: UNKNOWN
```

Official SWE-bench v5 remains final grading authority. Harbor remains the replaceable execution substrate.
