# Benchmark migration Phase 0–1

This branch starts from frozen public benchmark HEAD
`daa77eabfcef07c9799cc5311b04410a89b9dec1`. PR #8 remains the rollback/reference
implementation and stays draft; this migration does not change `main` or the private ADCP pin.

## Boundary

The custom generic benchmark substrate is frozen. Phase 0–1 adds only the research-owned
experiment contract and an official SWE-bench v5 grading boundary. No existing discovery,
environment reconstruction, native execution, evaluator, or qualification code is deleted yet.

Preserve as research semantics:

- canonical identities, content digests, provenance and CAS;
- paired/N-way assignment and experiment identity;
- model-token, request, cost and wall-clock budget policy;
- stock/ADCP agent adapters and normalized telemetry;
- reference-leakage and final-evaluator separation policy;
- paired statistics and reproducibility metadata.

Preserve as migration adapters/reference until later gates:

- current ADCP loading/role cycle and spend accounting;
- current independent evaluator and Click qualification canary;
- current result/CAS export paths.

Keep experimental, but remove from the primary benchmark critical path after migration:

- `corpus/qualification/` historical acquisition and qualification machinery;
- native/Windows execution and launch tooling;
- dependency/tox/local-plugin/wheel/sdist reconstruction;
- empty/reference qualification controls for newly built corpora.

Do not delete any of these in Phase 0–1.

## Canonical ExperimentManifest

`benchmark_core.experiment_manifest.ExperimentManifest` pins the scientific identity of a
trial independently of its execution engine. It records:

- dataset/version/task, task-repository commit, image digest and evaluator version;
- agent implementation/commit/configuration/ablation flags;
- exact model identifier/provider route/decoding/pricing snapshot;
- input/output/total model-token caps plus request, wall-time and patch safety caps;
- replaceable execution engine/provider/resource/network policy;
- repeat, seed and timestamps;
- patch, trajectory, telemetry digests and final evaluator result.

Harbor is intentionally not the domain model. A later Harbor adapter will map this contract
onto Harbor Job/Trial/Environment objects.

## Official SWE-bench v5 parity gate

Primary grading authority is the official SWE-bench CLI, currently pinned by the Phase 1
plan to `swebench==5.0.2`. The task repository is pinned separately. The wrapper in
`benchmark_core.swebench_v5` only constructs official CLI commands, writes official
prediction JSONL, and reads official `results.json`; it does not reproduce grading logic.

The fixed initial parity cohort lives at `migration/swebench_v5_verified_parity.json` and
contains ten SWE-bench Verified tasks across ten repositories. The gate is:

```text
same fixed cohort
    empty predictions
        -> every task is empty_patch_ids
        -> zero resolved/infra/ambiguous/error outcomes

same fixed cohort
    official --gold
        -> every task is resolved_ids
        -> zero unresolved/empty/infra/ambiguous/error outcomes
```

Run in a Linux environment capable of official SWE-bench v5 evaluation:

```text
python tools/verify_swebench_v5_parity.py \
  --task-repo /absolute/path/to/pinned/swe-bench-tasks
```

The tool fails closed if the installed SWE-bench version or task-repository commit differs
from the plan. On success it writes
`artifacts/swebench-v5-parity/PHASE1_SWEBENCH_V5_PARITY.json`.

This is evaluator qualification only. It makes no model calls and is not an A/B result.

## Legacy Click migration canary

Keep the already-qualified native historical control unchanged:

```text
pallets/click issue #2813 / PR #2816
base      1c68e531ef5e45f6facdb777c720d0f984614b81
reference 4f936ac1981645488f396953bc59e50445de00b6
FAIL_TO_PASS 1
PASS_TO_PASS 143
empty FAIL
reference PASS
exact replay PASS
```

This canary proves that migration has not erased the previously demonstrated invariants.
It is not required to become a permanent headline benchmark instance.

## Phase 1 acceptance

Phase 1 is complete only after actual Linux execution produces evidence that:

1. the ten-task cohort uses the pinned task repo and official evaluator identity;
2. all empty controls fail specifically as empty patches;
3. all official gold controls resolve;
4. no task is accepted through SKIP, infrastructure failure, ambiguity or evaluator error;
5. the legacy Click canary remains reproducible from the frozen implementation.

Only after this gate should Harbor substrate work start. No old generic infrastructure is
removed merely because the new contract has landed.
