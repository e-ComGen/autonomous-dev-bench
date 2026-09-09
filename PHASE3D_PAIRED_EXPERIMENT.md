# Phase 3D — paired causal experiment controller

Phase 3D adds the experiment-level controller that relates the two atomic coding trials used by the first causal Stock-vs-ADCP comparison.

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
same seed

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

`PaidAdmissionSnapshot.from_repository(...)` reads and content-binds these accepted locks:

- `DEEPSEEK_V4_ESTIMATOR.lock.json`;
- `ADCP.lock.json`;
- `DEEPSEEK_HARNESS.lock.json`.

Paid admission checks the expected model `deepseek-v4-flash` and provider route `deepseek-official`, then requires all production qualification facts to be PASS/ready.

The current repository intentionally remains blocked because:

```text
DEEPSEEK_LIVE_PROMPT_USAGE_PARITY_NOT_PASS
DEEPSEEK_ESTIMATOR_NOT_PAID_READY
ADCP_PRIVATE_PINNED_RUNTIME_NOT_PASS
ADCP_NOT_PAID_READY
```

When `paid=True`, `PairedExperimentController` validates this admission snapshot **before invoking either arm executor**. A blocked paid run therefore cannot make a Stock call first and only later discover that ADCP is not qualified.

`tools/phase3d_paid_preflight.py` exposes the same check as machine-readable JSON and makes no model call.

## Dry-run boundary

Dry-run mode exists to qualify experiment orchestration without spending model tokens. If either executor reports `model_called=true`, the controller rejects the run with `DryRunModelCallForbidden`.

Dry-run PASS is evidence about pair orchestration only. It cannot be promoted to a paid result.

## Accepted controller qualification

CI run `34357064416` on head `00b734b816262b4525518baea4314fdb9be6bc2b` passed:

- dependency firewall;
- Ubuntu Python 3.11 / 3.12 / 3.13 pytest + build;
- Windows Python 3.11 / 3.12 / 3.13 pytest + build.

No model or paid-provider call was made.

Machine-readable state is recorded in `PHASE3D.lock.json`.

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
PHASE3D_PAID_ADMISSION: BLOCKED
PAID_PAIRED_AB: NOT_RUN
WINNER: UNKNOWN
```

Official SWE-bench v5 remains final grading authority. Harbor remains the replaceable execution substrate.
