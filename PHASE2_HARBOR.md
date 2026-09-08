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

Harbor remains optional so the benchmark core stays installable/testable on Python 3.11.

## Windows-first host model

The primary physical host for this project is Windows. The exact Harbor `0.22.0` pin does not expose a dedicated native-Windows execution environment, so Phase 2 does not pretend that official SWE-bench tasks are Windows-native.

The supported primary path is:

```text
Windows physical PC
  -> PowerShell entrypoint
  -> WSL2 controller boundary
  -> Docker Desktop Linux engine
  -> Harbor Docker environment
  -> Linux task container
  -> official SWE-bench-compatible semantics
```

This means Linux is a property of the isolated benchmark task container, not a requirement for the physical machine. No cloud provider is required.

The one-command host qualification entrypoint is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\qualify_windows_host.ps1
```

It fails closed unless all of these are true:

- physical host is Windows;
- the selected/default WSL distribution is WSL2;
- Docker Desktop is reachable from Windows;
- Docker reports `OSType=linux`;
- a real Linux container executes successfully;
- Docker is reachable inside WSL2;
- Python >=3.12 is available inside WSL2;
- exact Harbor version and source commit match `HARBOR.lock.json`;
- the accepted no-model Harbor substrate trial passes through Docker;
- the existing independent substrate validator passes;
- final evidence is emitted as `artifacts/harbor-phase2/windows-host/PHASE2_WINDOWS_HOST.json`.

The qualification does not call a model and does not require any API key.

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

The official re-grade workflow is frozen to `workflow_dispatch` after acceptance so later host/documentation commits do not repeatedly rebuild SWE-bench images.

## Patch-boundary correction

Qualification found a real transport bug: a Harbor environment can contain pre-existing untracked/generated files before the agent runs. Exporting all untracked paths produced a contaminated patch.

`HarborWorkspaceFacade` now records the baseline untracked set before agent execution. Final patch export contains tracked changes plus only newly-created untracked paths. Dirty tracked baselines fail closed. Regression coverage preserves this invariant.

## Optional cloud challenger

Daytona remains pinned only as an optional remote-provider challenger. It is not a Phase 2 requirement, no `DAYTONA_API_KEY` is required for the Windows-first path, and an unrun Daytona workflow does not block Phase 2 acceptance.

## Phase 2 exit

The only host-specific evidence still required is a real run on the intended Windows PC producing:

```text
scope: PHASE2_WINDOWS_PHYSICAL_HOST_HARBOR_DOCKER_QUALIFICATION
status: PASS
physical_host_os: windows
execution_backend: docker_desktop_linux_engine
model_called: false
```

Current state:

```text
LOCAL_HARBOR_SUBSTRATE: PASS
LIFECYCLE_CANCELLATION_NETWORK_RESOURCES: PASS
STOCK_DEEPSEEK_HARBOR_TRANSPORT: PASS
IMMUTABLE_CAS_EXPORT: PASS
OFFICIAL_SWEBENCH_V5_REGRADE_BOUNDARY: PASS
WINDOWS_PHYSICAL_HOST: NOT_RUN
OPTIONAL_DAYTONA_CHALLENGER: NOT_REQUIRED
PHASE2: BLOCKED_ONLY_ON_WINDOWS_HOST_QUALIFICATION
```

The shared ModelBudgetGateway and ADCPAgent remain Phase 3 work.
