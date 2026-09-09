# Phase 3 — shared model budget gateway + ADCP arm

Base: clean Phase 2 `main` at `5dc8aee59e1ea4b2e2e998d501faad30efc7cb81`.

Phase 3 introduces the causal A/B model-call boundary. It does **not** change the accepted Harbor substrate, official SWE-bench v5 grading authority, fixed cohort, private ADCP production pin, or Phase 0–2 evidence.

## Scientific invariant

The first paid comparison remains:

```text
same task
same DeepSeek model
same model route
same primary total-model-token budget

Arm A: stock DeepSeek coding agent
Arm B: DeepSeek + ADCP orchestration
```

The primary fairness budget is `total_model_tokens`. Input, output, reasoning, cache, USD cost, wall time and request count are recorded separately for audit and secondary analysis.

No paid paired result exists yet and no ADCP superiority claim is made.

## Phase 3A — shared budget authority

`benchmark_core.model_budget.ModelBudgetGateway` is the research-owned budget authority. A model call must reserve a worst-case token envelope before dispatch and commit observed provider usage afterward.

Properties:

- hard `input_token_cap` enforcement;
- hard `output_token_cap` enforcement;
- hard primary `total_model_token_cap` enforcement;
- hard `max_requests` enforcement;
- concurrent/open reservations consume capacity before dispatch;
- unused reservation capacity is refunded on commit/cancel;
- observed usage may not exceed its reservation;
- double commit/cancel and mismatched reservations fail closed;
- reasoning/cache/USD/wall-time counters remain separately auditable;
- explicit per-call total envelopes support providers whose total/reasoning telemetry is not identical to simple input+output accounting.

This component is neutral and must be shared by both arms.

## Phase 3B — cross-process model transport

**NOT YET ACCEPTED.**

The Stock Harbor runner currently receives a provider base URL directly. ADCP's pinned runtime uses its existing Harness role-port boundary. Before any paid experiment, both must be routed through one budgeted model transport backed by the shared authority above.

Required property:

> Neither Stock nor ADCP may possess an alternate provider credential/route that can bypass the experiment budget authority.

A post-hoc token report is insufficient for the paid A/B. The hard budget must be enforced before model dispatch.

## Phase 3C — ADCP Harbor adapter

**NOT YET ACCEPTED.**

Private production identity remains pinned:

```text
e-ComGen/autonomous-dev-control-plane
commit 285702063815280398b95ba8696566259c8b5b34
runtime packages.zone_development.assured_runtime.ZoneDevelopmentRuntime
integration existing v2 runtime role ports / Harness bridge
```

The public benchmark adapter must not vendor private runtime source. It should bind the pinned runtime through its existing Harness role-port API, preserve Architect != Coder != Reviewer != Verifier, and export only the benchmark patch/trajectory/telemetry boundary needed by Harbor and official SWE-bench grading.

A deterministic fake-model qualification must precede paid execution.

## Phase 3D — paid paired A/B

**NOT RUN.**

Only after 3A–3C pass may the benchmark execute paid paired trials. Official SWE-bench v5 remains the final grading authority. Harbor is still only the replaceable execution substrate.

## Current state

```text
PHASE0_1_CLEAN_MAIN: PASS
PHASE2_HARBOR_SUBSTRATE: PASS
PHASE2_WINDOWS_PHYSICAL_HOST: PASS
PHASE3A_MODEL_BUDGET_AUTHORITY: IMPLEMENTED / CI_PENDING
PHASE3B_SHARED_CROSS_PROCESS_MODEL_TRANSPORT: NOT_IMPLEMENTED
PHASE3C_ADCP_HARBOR_ADAPTER: NOT_IMPLEMENTED
PAID_PAIRED_AB: NOT_RUN
PHASE3: IN_PROGRESS
```
