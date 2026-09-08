# Phase 2 — Harbor substrate qualification

Base: accepted Phase 0–1 head `447352d3b9d60ae9c14d4532ce1ef6e6f113bdd1`.

This phase qualifies Harbor only as a replaceable execution/orchestration engine. Official SWE-bench v5 remains the grading authority, and no ADCP or paid model call is introduced here.

## Pinned upstream

`HARBOR.lock.json` pins both the published version and the exact source commit:

```text
harbor-framework/harbor
version 0.22.0
commit d4509bbd3804f4b408527f476d764dacd988791d
Python >= 3.12
```

The project dependency is optional so the existing Python 3.11 benchmark core remains installable and testable.

## First substrate gate

The no-model gate proves the narrow external-agent boundary before migrating Stock DeepSeek:

```text
Harbor Trial
  -> custom BaseAgent import path
  -> BaseEnvironment.exec
  -> git workspace mutation
  -> uncommitted binary patch extraction
  -> Harbor AgentContext telemetry persistence
  -> independent Harbor verifier
  -> host-side evidence validation
```

The probe must establish:

- `setup()` and `run()` of the custom external agent execute;
- the environment exposes an immutable `environment_id`;
- the agent observes the exact baseline git commit;
- workspace mutation survives through verifier execution;
- exported `PATCH.diff` represents the actual uncommitted repository change;
- Harbor `result.json` persists zero model tokens/cost and benchmark metadata;
- the independent verifier returns full reward;
- no model is called.

This gate deliberately does not claim timeout, cancellation, no-network, CPU/RAM enforcement, remote-provider support, StockDeepSeek compatibility, or official SWE-bench re-grade. Those are separate Phase 2 probes so a happy-path trial cannot hide missing lifecycle guarantees.

## Next gates

After the substrate gate passes:

1. timeout/cancellation probe;
2. network-policy probe;
3. resource-policy declaration/enforcement probe;
4. StockDeepSeekAgent using the existing DeepSeekHarness semantics;
5. patch export into autonomous-dev-bench CAS;
6. one resulting patch re-graded by the already-qualified official SWE-bench v5 boundary;
7. remote Linux provider qualification.

The shared ModelBudgetGateway and ADCPAgent remain Phase 3 work.
