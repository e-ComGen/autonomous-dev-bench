# Phase 3 — shared model budget gateway + ADCP arm

Base: Phase 3A main at `7650c62f126dba161a4da92d631895b81fd66e52`.

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

`benchmark_core.model_budget.ModelBudgetGateway` is the accepted research-owned budget authority. A model call reserves a worst-case token envelope before dispatch and commits observed provider usage afterward.

Accepted CI:

- run `34303270164` — PASS;
- run `34303452955` — PASS on the final Phase 3A head;
- firewall self-test PASS;
- Ubuntu Python 3.11 / 3.12 / 3.13 pytest + build PASS;
- Windows Python 3.11 / 3.12 / 3.13 pytest + build PASS.

Phase 3A merged to `main` as `7650c62f126dba161a4da92d631895b81fd66e52`.

## Phase 3B — cross-process model transport

A budgeted OpenAI-compatible proxy boundary is now implemented for deterministic qualification.

Properties:

- the benchmark arm receives only a proxy credential and proxy base URL;
- the real upstream provider credential remains controller-side inside the proxy process;
- exact model identity is enforced before dispatch;
- streaming requests must request terminal usage (`stream_options.include_usage=true`);
- every admitted request reserves input/output/total budget before upstream dispatch;
- SSE is relayed transparently while the proxy captures terminal provider usage;
- DeepSeek/OpenAI-compatible prompt/completion/total/cache/reasoning usage is committed to `ModelBudgetGateway`;
- any dispatched request lacking exact terminal usage becomes `accounting_unknown` and keeps its reservation open;
- unknown requests without an exact pre-dispatch estimate fail before upstream dispatch;
- there is no character-count or bytes-per-token heuristic fallback;
- `/usage` exposes the read-only experiment ledger for the runner;
- a standalone proxy process entrypoint exists for a real cross-process boundary.

The exact pinned DeepSeek Harness contract used for this design is `a66e4702047846cdaa10c66c9d3df3951f5ea70d`; its DeepSeek route emits streaming chat completions with `stream_options.include_usage=true` and terminal usage fields compatible with this proxy.

### Production blocker

The bundled estimator is intentionally `fixture_exact_request_map` only. It proves transport/budget enforcement on deterministic known requests but is **not** a production DeepSeek tokenizer.

Before a paid A/B, Phase 3B still requires a production exact tokenizer-aware estimator for dynamic DeepSeek wire requests. Paid mode must fail closed until that estimator is qualified. Approximate token heuristics are explicitly disallowed for the causal experiment.

Required property remains:

> Neither Stock nor ADCP may possess an alternate provider credential/route that can bypass the experiment budget authority.

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

Only after production 3B and 3C pass may the benchmark execute paid paired trials. Official SWE-bench v5 remains the final grading authority. Harbor is still only the replaceable execution substrate.

## Current state

```text
PHASE0_1_CLEAN_MAIN: PASS
PHASE2_HARBOR_SUBSTRATE: PASS
PHASE2_WINDOWS_PHYSICAL_HOST: PASS
PHASE3A_MODEL_BUDGET_AUTHORITY: PASS
PHASE3B_CROSS_PROCESS_PROXY_FIXTURE: IMPLEMENTED / CI_PENDING
PHASE3B_PRODUCTION_EXACT_TOKEN_ESTIMATOR: NOT_IMPLEMENTED
PHASE3C_ADCP_HARBOR_ADAPTER: NOT_IMPLEMENTED
PAID_PAIRED_AB: NOT_RUN
PHASE3: IN_PROGRESS
```
