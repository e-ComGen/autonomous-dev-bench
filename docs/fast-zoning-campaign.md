# FAST zoning campaign runner v1

This layer runs reproducible benchmark pairs. It does not grant production
TaskOwner authority and does not implement OMP, Auto-Zoning, or a context planner.
Qualified producers supply immutable A/B context packets and evaluator artifacts.

## Experimental contract

Every pair uses the same task, buggy Git snapshot, shared model configuration,
tools, limits, environment and predeclared evaluator plan. Only the supplied
context policy differs. The runner retains each exact packet and records its hash.
Native reads outside the initial zone remain available to both arms and count
towards resource usage.

The default supported command is OMP 18.1.14 with `--mode json --no-session`,
`alibaba-token-plan/deepseek-v4-pro`, `--auto-approve`, tools `read,edit,write`,
and `--max-time 10m`. It is configuration, not a new runtime.

Validation and planning do not invoke a model. Execution requires explicit
authorization. A reused run ID or invocation marker must not replay an arm.
After an infrastructure failure, record the failed pair; a new attempt requires
a new pair run ID and two fresh workspaces.

## Isolation and evidence

The source repository is read-only to the campaign. Each arm gets an independent
clone with the exact buggy HEAD and tree and an initially empty Git status.
Sessions, transcripts, patches and evaluation workspaces are separate. Candidate
capture includes tracked, untracked and ignored files through a temporary Git
index, preserving binary and mode changes without modifying the candidate index.
Evaluation replays the complete patch into a fresh buggy checkout.

Evaluator material and hidden metadata are never interpolated into the model
packet. Known hidden/gold material must be declared for leakage checks. Such
checks reject declared material and forbidden metadata, but cannot prove absence
of an undisclosed secret or a semantic paraphrase. This is experimental evidence
isolation, not an adversarial operating-system sandbox.

## Result semantics

The primary result records every evaluator separately. An invalid patch cannot
qualify. Semantic success requires every required, predeclared evaluator to pass.
Missing, ERROR or NOT_RUN evidence cannot silently become success. Optional checks
remain explicit. Repair classification requires deterministic evidence; insufficient
evidence yields INCONCLUSIVE.

Post-hoc analysis is stored separately and does not rewrite PRIMARY_RESULT.
Pair 1's later differential review stays post-hoc. The Pair 2 fixture preserves
BOTH_FAIL. The Pair 3 fixture preserves equivalent predeclared semantic success
and approximately 32.4335% provider-token saving.

## Resource accounting

Usage is summed across assistant `message_end` records. `cacheRead` is summed,
not maximized; the final message's token count is not a session total. Unknown
counters remain unknown. Exit code zero and the final terminal `agent_end` are
both required for successful OMP transport. Transport success is separate from
semantic success.

Read metrics retain exact requested paths, including failed attempts. Unique-file
counts normalize supported range selectors and prefer resolved paths; directory
listings are not files. Raw JSONL and stderr remain separate evidence artifacts.
Provider-reported zero cost is not proof of zero monetary marginal cost.

Campaign reports separate quality counts/rates from resource distributions.
Mean, median, min and max resource changes use only valid equal-quality-success
pairs. Failed, unequal-quality and infrastructure-failed pairs are not pooled
into one global zoning-saving percentage. Rate denominators are reported explicitly.

## Overnight handoff

Use the [versioned schema](../packages/benchmark_core/benchmark_core/fast_zoning/task.v1.schema.json)
and [manifest template](../examples/fast_zoning/task.v1.example.json). Template
zero hashes and placeholder paths intentionally cannot pass runtime validation.

Before handing a task to this runner, the producer must finish benchmark
qualification, freeze its evaluator identities and hashes, and supply the versioned
manifest described by the packaged schema. The runner does not infer missing
fields from chat history or manufacture qualification. A proposal or a manifest
with unresolved references is not executable.

Keep hidden root causes, known fixes and evaluation corpora outside model workspaces.
Maintain the same manifest and final packet bytes throughout a pair. A changed
manifest or artifact requires a new validated pair run, not a one-arm retry.

## CLI

Install this repository into the environment with `python -m pip install -e .`.
The dedicated module keeps existing benchmark CLI commands unchanged:

```text
python -m cli.fast_zoning campaign validate task.json --output validation.json
python -m cli.fast_zoning campaign plan task.json --campaign-dir campaigns/night-01 --pair-run-id pair-001 --dry-run
python -m cli.fast_zoning campaign execute campaigns/night-01/tasks/ID-01/pair-001 --dry-run
python -m cli.fast_zoning campaign summarize campaigns/night-01
```

Planning validates source snapshots and artifacts and prepares fresh independent
copies; it does not call OMP, even for a version check. A future authorized run
uses `campaign execute <pair-dir> --authorize-model-execution`. Do not supply that
flag merely to validate or inspect a campaign. A second attempt requires a new
pair ID and planning both arms again.

The task manifest has `schema_version: 1`, a shared `execution` configuration,
`contexts.A` and `contexts.B`, and a frozen `evaluation_plan`. B's `zoning`
contains its zone ID, repository-relative artifact paths, snapshot ID and analysis
digest. Optional per-context timing fields are seconds. Missing timing or provider
usage stays unknown instead of becoming zero.

`task_hash` is SHA256 of the UTF-8 task text. `evaluation_plan_digest` is SHA256
of canonical JSON for the plan: sorted keys, compact separators, UTF-8 with
non-ASCII characters unescaped, and no non-finite numbers. Use the public
`benchmark_core.fast_zoning.manifest.plan_digest` helper. Relative artifact paths
are relative to the manifest; zone-owned paths are relative to its repository.
Run order is SHA256 parity of the UTF-8 seed: even A_THEN_B, odd B_THEN_A.

## Evaluator handoff protocol

Declare all five categories explicitly: `existing_suite`, `targeted_oracle`,
`differential_check`, `metamorphic_check`, `cross_component_check`. Each evaluator
has an ID, required boolean, identity, timeout, command argument array and hashed
artifacts. Commands run without a shell. `{workspace}` names the fresh candidate
checkout; `{artifact0}`, `{artifact1}`, and so on reference verified artifacts.
Bind the evaluator payload itself, not an unrelated file, to those hashes.

The trusted evaluator writes one JSON object to stdout with `status` equal to
PASS, FAIL or ERROR. Extra logs belong on stderr. A semantic FAIL must be explicit;
missing/malformed JSON, timeout, or a nonzero exit claiming PASS is ERROR. The
producer must ensure evaluator imports, reference data and runtime dependencies
are pinned appropriately; hashing one script is not proof of its entire environment.

Never point an evaluator command at an unqualified overnight proposal. The producer
must first validate buggy failure and known-fix success under its complete plan.

## Qualification import bridge

The explicit `qualification-v1` to `campaign-schema-v1` bridge preserves the
source evaluation digest. It does not claim that a translated representation has
the same bytes or hash. A separate campaign-manifest digest and import-binding
digest bind source provenance, task hash, evaluator identities and importer version.

Importer version: `qualification-to-campaign-v1.0.0`. Machine contracts:
[import envelope](../packages/benchmark_core/benchmark_core/fast_zoning/qualification-import.v1.schema.json),
[packet-build request](../packages/benchmark_core/benchmark_core/fast_zoning/packet-build-request.v1.schema.json),
and [packet-build output](../packages/benchmark_core/benchmark_core/fast_zoning/packet-build-output.v1.schema.json).

```text
python -m cli.fast_zoning campaign import-qualification SOURCE_REPO BENCHMARK_REPO ID-01 --bundle-dir imports/ID-01 --run-order-seed expansion-v1-20260916:ID-01
python -m cli.fast_zoning campaign validate-import imports/ID-01
python -m cli.fast_zoning campaign bind-packets imports/ID-01 contexts.json --bundle-output imports/ID-01-ready
```

Import derives frozen status only from checked qualification evidence: ready,
no model execution, known fix reset, correct source/task digests, valid evaluator
artifacts, and exact clean/buggy snapshot bindings. All evaluator categories and
required flags survive translation. Source qualification plans remain unchanged.

Without real A/B packets the result is `IMPORTED_NOT_EXECUTABLE`, with valid source
import and `EXECUTION_READY=NO_MISSING_PACKETS`. This is a valid intermediate state,
not an executable campaign task. The emitted packet-build request delegates normal
non-zoned and real zone-aware context construction to cache-harness-addon. This
repository implements no additional planner and fabricates no packets.

Binding verified packets creates a new bundle and runs the existing campaign
validator. Hidden qualification data stays private; only the allowlisted public
task and snapshot data enter the model-visible manifest and packet request.
Neither import, validation, nor packet binding invokes OMP or a model.

## Morning inspection

The campaign stores its identity, per-task snapshot, pair plan, seal and state.
Every arm has raw JSONL, stderr, metrics, complete patch and evaluator results.
Exclusive execution and arm claims prevent crash recovery from silently replaying
a model invocation. A RUNNING state with no completion remains inspectable; the
operator must start a new pair ID instead of treating it as an automatic retry.

`campaign summarize` builds a campaign-level report from durable pair artifacts.
Keep incomplete and invalid runs visible; only completed valid equal-quality
successes contribute to resource distributions.
