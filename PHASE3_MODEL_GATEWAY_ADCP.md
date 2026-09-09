# Phase 3 — shared model budget gateway + ADCP arm

Base: clean `main` at `5dc8aee59e1ea4b2e2e998d501faad30efc7cb81` (accepted Phase 0–2).

Status: **IN_PROGRESS**. No paid stock-vs-ADCP experiment has run and no ADCP superiority claim is made.

## Scientific invariant

Both experimental arms must consume the same model through the same model-budget authority.

Primary fairness metric:

```text
total_model_tokens = input_tokens + output_tokens
```

The benchmark also records input, output, reasoning, cache, cost, wall time and request count separately. Reasoning/cache dimensions are diagnostic subsets and are not added again to the primary total.

## Shared model gateway

`ModelBudgetGateway` is the thread-safe per-arm ledger. It admits requests, reserves concurrent output allowance, records provider-reported usage and fails future admissions after a hard-cap violation.

`SharedModelGateway` is an authenticated OpenAI-compatible non-streaming proxy. Agent containers receive only:

```text
AUTOBENCH_MODEL_GATEWAY_URL
AUTOBENCH_MODEL_GATEWAY_USAGE_URL
AUTOBENCH_MODEL_GATEWAY_TOKEN
```

The upstream provider credential remains controller-side. The gateway verifies the exact model identity, refuses unqualified streaming, settles usage from the provider response and exposes an authenticated usage snapshot.

Production `StockDeepSeekAgent` now requires this shared route. The old direct fake provider is preserved only behind the explicit `AUTOBENCH_FAKE_MODEL=1` Phase 2 qualification flag.

## ADCP arm boundary

The benchmark does **not** implement Architect → Coder → Reviewer → Verifier/BADC itself.

Pinned private runtime identity:

```text
repository:
  e-ComGen/autonomous-dev-control-plane
commit:
  285702063815280398b95ba8696566259c8b5b34
runtime:
  packages.zone_development.assured_runtime.ZoneDevelopmentRuntime
integration:
  existing-v2-runtime-role-ports
```

`ADCPAgent` is only a Harbor transport adapter. The paid-run task image must stage a runner at `/opt/autobench/run_adcp.py`; that runner loads the exact private pin and maps benchmark inputs to the runtime's existing public contracts. The result must attest the exact runtime identity, shared model route, no direct model API, role evidence and authoritative gateway accounting.

## Committed candidate patch boundary

The private Zone Development runtime commits validated candidate snapshots inside the isolated supplied worktree. Therefore a plain final `git diff` can be empty even when the agent successfully changed the repository.

`HarborWorkspaceFacade.git_diff_since()` now:

1. captures the original task HEAD;
2. requires final HEAD to descend from that baseline;
3. diffs the original baseline commit against the final working tree;
4. appends only newly-created untracked files.

This works for both stock agents that leave changes uncommitted and ADCP candidates that advance HEAD.

## No-model ADCP transport qualification

`tests/harbor_phase3_adcp` contains a deterministic transport stub, **not** an ADCP implementation. It attests the exact private runtime identity, performs zero model calls, creates a committed candidate and returns valid zero-usage shared-gateway accounting. The corresponding Harbor workflow verifies that the committed candidate is exported as the final patch and that the fake gateway token does not leak into artifacts.

## Remaining gates before any paid A/B

Phase 3 is not complete until all of the following are qualified:

1. real HTTP transport through `SharedModelGateway` against a deterministic fake upstream;
2. Stock DeepSeek Harness through that shared gateway inside Harbor;
3. exact pinned private ADCP runtime through that same gateway;
4. paired fairness-budget/accounting parity;
5. either streaming support qualification or an explicit invariant that both arms use non-streaming requests;
6. only then a small paid paired canary;
7. only after the canary, the real fixed-cohort stock-vs-ADCP experiment.

Phase 3 infrastructure results must never be described as evidence that ADCP is better than stock.
