# Phase 3 — shared model budget gateway + ADCP arm

Base: Phase 3B proxy `main` at `a6d81d39a036c7e98ddad124b6eda5a2bdec89e4`.

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

The deterministic cross-process proxy qualification is accepted and merged to `main` as `a6d81d39a036c7e98ddad124b6eda5a2bdec89e4`.

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
- a standalone proxy process entrypoint proves a real cross-process credential/budget boundary.

The exact pinned DeepSeek Harness contract used for this design is `a66e4702047846cdaa10c66c9d3df3951f5ea70d`; its DeepSeek route emits streaming chat completions with `stream_options.include_usage=true` and terminal usage fields compatible with this proxy.

Accepted CI:

- run `34304155920` — PASS;
- final documentation head run `34304268061` — PASS;
- firewall self-test;
- Ubuntu Python 3.11 / 3.12 / 3.13 pytest + build;
- Windows Python 3.11 / 3.12 / 3.13 pytest + build;
- in-process HTTP proxy qualification;
- real subprocess proxy qualification;
- fail-closed unknown-estimate and missing-usage paths.

### Production DeepSeek-V4 estimator — offline boundary accepted

The estimator is pinned to the official DeepSeek V4 Flash 0731 release:

```text
repo: deepseek-ai/DeepSeek-V4-Flash-0731
revision: 9e165c30e2704aec5d9d593cce3eebd58bbef1cb
encoder: encoding/encoding_dsv4.py
model route under test: deepseek-v4-flash
```

`DeepSeekV4RequestEstimator` delegates prompt construction to the pinned official encoder instead of reimplementing the template, then uses the pinned tokenizer's `encode(prompt)` count for pre-dispatch input accounting.

The paid boundary is intentionally fail-closed:

- unknown prompt-affecting top-level wire fields are rejected;
- ambiguous/missing thinking state is rejected;
- text-only Flash qualification rejects multimodal content;
- tool calls require exact IDs and OpenAI function-wire shape;
- tool-bearing requests require a system/developer encoder anchor rather than inventing one;
- `max_tokens` must be explicit and positive;
- no character-count or byte-count token heuristic exists.

Accepted offline qualification:

```text
workflow run: 34347337284
head: fa64a6f72c84a76446b272f951ae4f224f330da3
artifact: 10102254727
artifact digest: sha256:47741fbcdaba2c2009a23467b5c0362333473f0f05438b52d4b86e7dbe8483a6
status: PASS
paid_model_called: false
```

The evidence proves:

- all four unchanged official `test_encoding_dsv4.py` golden cases PASS;
- pinned official encoder SHA256 `abc0d26120250dda0ae077dc64aa28836026e61e970854aaeb792445e6a0dde6`;
- pinned official encoder-test SHA256 `c2bc54c4c934f5c64096bd9c555efa7d1ddf179c1eff58f01ceb2dcd60adcf28`;
- benchmark wire case 1 renders byte-for-byte the official golden prompt;
- both prompt hashes equal `9b366d9d2eac842a6e890594aac0b58648e5623717202b33497afadf03e26540`;
- pinned tokenizer loads fully offline after bootstrap;
- case-1 exact input count is `541` tokens;
- with `max_tokens=128`, pre-dispatch envelope is `669` total tokens;
- pinned tokenizer SHA256 is `8f9f37ca37fdc4f5fd36d5cf4d3b0e8392edb4e894fd10cc0d70b4957c8633cf`.

Offline PASS does **not** make the estimator paid-ready. DeepSeek provider-reported `usage.prompt_tokens` remains the final production accounting authority; live prompt-usage parity is a separate required gate and has not been run. The lock therefore deliberately remains:

```text
live_provider_prompt_usage_parity: false
paid_ready: false
production_blocker: LIVE_PROVIDER_PROMPT_USAGE_PARITY_NOT_RUN
```

A separate no-call verifier exists for a later authenticated capture; it cannot itself contact DeepSeek or spend model budget.

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
PHASE3B_CROSS_PROCESS_PROXY_FIXTURE: PASS
PHASE3B_DEEPSEEK_V4_ESTIMATOR_OFFLINE: PASS
PHASE3B_LIVE_PROVIDER_PROMPT_USAGE_PARITY: NOT_RUN
PHASE3B_PRODUCTION_PAID_READY: NO
PHASE3C_ADCP_HARBOR_ADAPTER: NOT_IMPLEMENTED
PAID_PAIRED_AB: NOT_RUN
PHASE3: IN_PROGRESS
```
