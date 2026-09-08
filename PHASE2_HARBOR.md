# Phase 2 — Harbor substrate qualification

Base: accepted Phase 0–1 head `447352d3b9d60ae9c14d4532ce1ef6e6f113bdd1`.

This phase qualifies Harbor only as a replaceable execution/orchestration engine. Official SWE-bench v5 remains the grading authority. No ADCP superiority claim and no paid model result is introduced here.

## Pinned upstream

`HARBOR.lock.json` pins:

```text
harbor-framework/harbor
version 0.22.0
commit d4509bbd3804f4b408527f476d764dacd988791d
Python >= 3.12
```

The remote-provider qualification additionally pins Daytona SDK `0.192.0` and its published wheel SHA256. Harbor remains optional so the benchmark core stays installable/testable on Python 3.11.

## Accepted internal gates

The following capabilities have real GitHub Actions evidence and are accepted:

- Harbor external `BaseAgent` boundary and workspace mutation;
- timeout/lifecycle handling;
- explicit cancellation;
- agent-phase no-network enforcement;
- CPU/RAM cgroup enforcement;
- deterministic patch extraction with pre-existing untracked files excluded from the agent delta;
- Stock DeepSeek Harness transport through Harbor using a deterministic fake model;
- exact DeepSeek Harness wheel/runtime identity and token/request accounting;
- immutable content-addressed trial export into benchmark CAS;
- Harbor patch transport followed by independent official SWE-bench v5 re-grade.

Key accepted runs:

```text
Harbor substrate/lifecycle/cancellation:
  run 34270222144

Stock DeepSeek Harness fake-model transport:
  run 34271926970
  status PASS
  verifier reward 1.0
  paid model called false

Stock transport + immutable CAS export:
  run 34272593892
  status PASS
  CAS status PASS

Harbor -> official SWE-bench v5 transport re-grade:
  run 34282501941
  head c68b8db431704ae1016479ee13e017987c76d504
  Harbor reward 1.0
  patch bytes 224
  official evaluator completed 1/1
  infra failures 0
  ambiguous failures 0
  empty patches 0
  evaluator errors 0
  official outcome UNRESOLVED (expected for the deliberate marker-only transport patch)
  boundary status PASS
```

The official re-grade workflow is frozen to `workflow_dispatch` after acceptance so later documentation/provider commits do not repeatedly rebuild SWE-bench images.

## Patch-boundary correction

Qualification found a real transport bug: a Harbor environment can contain pre-existing untracked/generated files before the agent runs. Exporting all untracked paths produced a contaminated patch.

`HarborWorkspaceFacade` now records the baseline untracked set before agent execution. Final patch export contains tracked changes plus only newly-created untracked paths. Dirty tracked baselines fail closed. Regression coverage preserves this invariant.

## Remaining Phase 2 gate: Daytona remote Linux

Phase 2 is **not yet fully accepted**. The only remaining acceptance gate is a real remote Linux execution through Harbor's Daytona environment.

The gate is implemented in:

```text
.github/workflows/phase2-harbor-daytona.yml
suites/coding/harbor/daytona_probe_agent.py
tools/verify_harbor_phase2_daytona.py
```

It requires repository Actions secret:

```text
DAYTONA_API_KEY
```

The remote gate must prove all of the following before Phase 2 can become PASS:

- Harbor reports environment type `daytona`;
- an actual Daytona sandbox id exists (only its SHA256 is persisted);
- execution reports Linux and records architecture;
- the same workspace patch boundary works remotely;
- independent verifier reward is 1.0;
- input/cache/output model token counters and cost are zero;
- no paid model is called;
- the controller `DAYTONA_API_KEY` value is absent from persisted trial artifacts.

Because a newly-added `workflow_dispatch` workflow cannot be manually dispatched before it exists on the default branch, this PR also supports a same-repository `pull_request` trigger scoped only to:

```text
migration/daytona_remote_qualification.trigger
```

After `DAYTONA_API_KEY` is configured, creating/updating that trigger file starts the qualification without merging Phase 2 to `main`. Fork pull requests are excluded from the credentialed job.

## Phase 2 exit

Phase 2 becomes PASS only after a real Daytona artifact contains:

```text
scope: PHASE2_HARBOR_REMOTE_PROVIDER_DAYTONA
status: PASS
```

Until then the precise state is:

```text
LOCAL_HARBOR_SUBSTRATE: PASS
LIFECYCLE_CANCELLATION_NETWORK_RESOURCES: PASS
STOCK_DEEPSEEK_HARBOR_TRANSPORT: PASS
IMMUTABLE_CAS_EXPORT: PASS
OFFICIAL_SWEBENCH_V5_REGRADE_BOUNDARY: PASS
REMOTE_DAYTONA_PROVIDER: NOT_RUN
PHASE2: BLOCKED_ON_REMOTE_PROVIDER_CREDENTIAL_AND_RUN
```

The shared ModelBudgetGateway and ADCPAgent remain Phase 3 work.
