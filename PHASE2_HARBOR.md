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

## Accepted Windows-first host model

The intended physical benchmark host is Windows. Exact Harbor `0.22.0` has no dedicated native-Windows execution environment, so official SWE-bench tasks remain Linux-container based.

The accepted primary path is:

```text
Windows physical PC
  -> PowerShell controller
  -> WSL2 / Ubuntu 24.04
  -> Docker Engine inside WSL2
  -> Harbor Docker environment
  -> Linux benchmark task container
  -> official SWE-bench-compatible semantics
```

Docker Desktop is not required for the accepted Phase 2 path. Daytona remains optional.

The Windows bootstrap/qualification policy is deliberately non-persistent:

- no `RunOnce` continuation;
- no Startup entry;
- no scheduled task;
- no automatic reboot;
- no Windows background persistence;
- if a reboot is required, the run stops and the same bootstrap is launched manually again;
- Docker Engine is installed inside the qualification WSL2 distro;
- Docker/containerd autostart is disabled for the qualification path;
- the Docker daemon is started only for the qualification session when needed.

The qualification does not call a model and requires no model/API credential.

## Accepted Windows physical-host evidence

A real run on the intended physical Windows machine completed successfully on 2026-09-09.

Observed qualification result:

```text
scope: PHASE2_WINDOWS_PHYSICAL_HOST_HARBOR_DOCKER_QUALIFICATION
status: PASS
physical_host_os: windows
controller_boundary: powershell_to_wsl2
execution_backend: wsl2_docker_engine
task_environment_os: linux_container
native_windows_harbor_claimed: false
official_swebench_semantics_preserved: true
bootstrap_mode: manual_reboot_no_persistence
persistence_created: false
automatic_reboot: false
model_called: false
```

Runtime identity:

```text
WSL distro: Ubuntu-24.04
WSL kernel: 6.18.33.2-microsoft-standard-WSL2
Python: 3.12.3
Docker Engine: 29.8.0
Container probe: Linux x86_64
Harbor version: 0.22.0
Harbor commit: d4509bbd3804f4b408527f476d764dacd988791d
Harbor trial reward: 1.0
```

Evidence integrity:

```text
host_evidence_sha256:
328a807a699918ab69f6d49a88a6b1b889e39e6d52343c310325f4caf11ea917

trial_tree_sha256:
e98ea3e812228657c65c4929d19f83388905ca6bfbb293c143a540c0366d909d
```

The accepted run also passed the existing independent substrate validator and emitted `artifacts/harbor-phase2/windows-host/PHASE2_WINDOWS_HOST.json`.

## Accepted internal gates

The following capabilities have real evidence and are accepted:

- Harbor external `BaseAgent` boundary and workspace mutation;
- timeout/lifecycle handling;
- explicit cancellation;
- agent-phase no-network enforcement;
- CPU/RAM cgroup enforcement;
- deterministic patch extraction with pre-existing untracked files excluded from the agent delta;
- Stock DeepSeek Harness transport through Harbor using a deterministic fake model;
- exact DeepSeek Harness wheel/runtime identity and token/request accounting;
- immutable content-addressed trial export into benchmark CAS;
- Harbor patch transport followed by independent official SWE-bench v5 re-grade;
- physical Windows host -> WSL2 -> Docker Engine -> Harbor qualification.

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

The official re-grade workflow remains frozen to `workflow_dispatch` after acceptance so later documentation/host commits do not repeatedly rebuild SWE-bench images.

## Patch-boundary correction

Qualification found a real transport bug: a Harbor environment can already contain untracked/generated files before the agent runs. Exporting all untracked paths contaminated a submission with unrelated generated content.

`HarborWorkspaceFacade` snapshots baseline untracked paths before agent execution. Final patch export contains tracked changes plus only newly-created untracked paths. Dirty tracked baselines fail closed. Regression coverage preserves this invariant.

## Optional challengers

Docker Desktop remains an optional Windows backend profile, not the accepted Phase 2 requirement.

Daytona remains pinned only as an optional remote-provider challenger. It is not a Phase 2 requirement, no `DAYTONA_API_KEY` is required for the accepted Windows path, and an unrun Daytona workflow does not block Phase 2 acceptance.

## Phase 2 exit

Current state:

```text
LOCAL_HARBOR_SUBSTRATE: PASS
LIFECYCLE_CANCELLATION_NETWORK_RESOURCES: PASS
STOCK_DEEPSEEK_HARBOR_TRANSPORT: PASS
IMMUTABLE_CAS_EXPORT: PASS
OFFICIAL_SWEBENCH_V5_REGRADE_BOUNDARY: PASS
WINDOWS_PHYSICAL_HOST: PASS
OPTIONAL_DAYTONA_CHALLENGER: NOT_REQUIRED
PHASE2: PASS
```

Phase 2 is complete. The shared ModelBudgetGateway and ADCPAgent remain Phase 3 work.
