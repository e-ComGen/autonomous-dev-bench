# Shared Benchmark Platform for Autonomous Software Engineering

## Executive decision and architectural invariant

**Decision: build it.** The right architecture is not a universal benchmark but a **shared experimental substrate with capability-local evaluation**.

The research evidence points strongly in this direction. Repository-level benchmarks such as SWE-bench already show why infrastructure quality cannot be treated as incidental: evaluation requires reproducible repositories, environments and tests, and OpenAI's verification work found that environment setup failures, underspecified tasks and overly narrow tests could materially distort measured capability. SWE-bench Verified therefore introduced human validation and more reliable containerized execution, while keeping evaluation tests hidden from the agent. citeturn18view0 Recent repository-level benchmark work goes further: RepoProbe argues that patch success does not by itself establish repository or architectural understanding, while RACE-bench explicitly separates final executable correctness from intermediate reasoning/stage evidence so that failures can be localized. citeturn7view0turn7view2

That is almost exactly the problem your autonomous-development platform faces.

| Decision | Recommendation |
|---|---|
| `SHOULD_BUILD_SHARED_BENCHMARK_PLATFORM` | **YES** |
| `SHOULD_IT_BE_SEPARATE_REPOSITORY` | **YES**, with a small publishable/reusable `benchmark_core` package |
| `SHOULD_REAL_PROJECT_CORPUS_BE_SHARED` | **YES** |
| `SHOULD_TASK_CORPUS_BE_SHARED` | **YES**, but suites receive capability-specific projections of a task |
| `SHOULD_ORACLES_BE_SHARED` | **Oracle mechanisms/primitives: yes. Capability verdict definitions, labels, thresholds and authority policies: no.** |
| `SHOULD_MUTATIONS_BE_SHARED` | **Mutation mechanics, metadata and semantic intent: yes. Expected capability response: suite-local.** |
| `SHOULD_FAULTS_BE_SHARED` | **YES**, with suite-local lifecycle expectations |
| `SHOULD_ENVIRONMENTS_BE_CACHED` | **YES**, only under exact content/environment fingerprints |
| `SHOULD_BASELINE_RESULTS_BE_CACHED` | **YES**, if source, environment, command specification and benchmark runner fingerprint all match |
| `SHOULD_ANALYSIS_RESULTS_BE_SHARED` | **Usually NO.** Only exact deterministic computations with complete dependency keys may be reused |
| `SHOULD_THERE_BE_ONE_SCORE` | **NO** |
| `SHOULD_FULL_SYSTEM_REPLACE_COMPONENT_TESTING` | **NO** |
| `SHOULD_PRODUCTION_DEPEND_ON_BENCHMARK` | **NEVER** |

The central invariant should be formalized as:

```text
SHARE:
    repositories
    immutable snapshots
    environments
    dependency downloads
    baseline health evidence
    task definitions
    mutation implementations
    fault implementations
    experiment runtime
    resource accounting
    provenance format
    artifact storage
    generic oracle primitives

DO NOT SHARE:
    capability conclusions
    capability labels
    suite acceptance thresholds
    suite authority policies
    hidden expected outputs
    architectural preference masquerading as truth
    "safe" certificates produced by the system under test
```

Or, more compactly:

```text
SHARED INPUTS
SHARED EXPERIMENTAL INFRASTRUCTURE
SHARED MECHANICS

            ↓

INDEPENDENT OBSERVATION
INDEPENDENT ORACLES
INDEPENDENT CAPABILITY EVIDENCE
INDEPENDENT HARD GATES
```

This matters because a single end-to-end `PASS` can conceal very different defects. A request may ultimately produce working code even though Auto-Zoning chose the wrong owner, Architecture Assurance admitted an invalid boundary, the coder accidentally crossed zones, Auto-Refactoring issued a false-safe certificate, or the harness performed a duplicate side effect after restart. Recent benchmark work similarly argues that final-patch-only evaluation is insufficient for diagnosing repository-level agent behaviour. citeturn7view2turn7view0

**There should therefore be no `AUTONOMOUS_DEV_SCORE = 87.3`.** Store a metric vector plus non-compensable gates:

```text
Hard gates
──────────
false_safe_certificate              == 0
unauthorized_cross_zone_write       == 0
half_applied_transaction            == 0
accepted_stale_candidate            == 0
lost_required_verification          == 0
evidence_integrity_failure          == 0

Capability vectors
──────────────────
AutoRefactoring:
    detection_precision
    detection_recall
    keep_current_accuracy
    semantic_preservation
    false_safe_rate

AutoZoning:
    responsibility_precision
    responsibility_recall
    ownership_accuracy
    cross_zone_false_positive_rate

ArchitectureAssurance:
    false_admission_rate
    false_rejection_rate
    escalation_accuracy

Harness:
    completion_rate
    restart_success
    duplicate_suppression
    retry_count
    budget_compliance
    cost
```

A system with perfect aggregate performance but one unauthorized write should still fail the corresponding release gate.

The platform should support five increasingly expensive evaluation levels:

```text
L0  static/component invariant
L1  deterministic subsystem
L2  LLM-assisted subsystem
L3  multi-agent pipeline
L4  end-to-end autonomous task
```

And four execution compositions:

```text
component    AutoRefactoring
subsystem    Coder → Refactoring → Verification
pipeline     TaskOwner → Zoning → Zone Development
full-system  User request → integrated CandidateSnapshot
```

A useful initial **scenario-count** heuristic is roughly `70% component / 20% subsystem / 8% pipeline / 2% full-system`. This is an engineering allocation, not a universal empirical law. Compute cost need not follow those percentages because a single L4 experiment may cost more than dozens of L0/L1 experiments. The important rule is that increasing E2E coverage must **not delete semantic component scenarios**.

For stochastic agent runs, the unit of evidence should be a distribution rather than a single lucky trajectory: report `successes / attempts`, confidence intervals, latency/cost distribution and seeds. Deterministic engines can ordinarily use one canonical run per exact input, supplemented by repeated restart/concurrency experiments where nondeterminism itself is under test.

## Platform boundary, repository architecture and APIs

The most important architectural decision is **Option D: separate benchmark repository + reusable benchmark-core package + a few genuinely neutral runtime/contracts packages outside the benchmark**.

Do not put everything under:

```text
autonomous-dev-control-plane/benchmarks/
```

because that makes benchmark dependencies, production dependencies and hidden evaluation logic progressively harder to separate. Equally, do not put generic worktree/evidence functionality only inside `autonomous-dev-bench` if production Harness legitimately needs the same generic capability.

The desired dependency structure is:

```text
                         ┌──────────────────────────┐
                         │      Production          │
                         │                          │
                         │ TaskOwner                │
                         │ Auto-Zoning              │
                         │ Architecture             │
                         │ Coder / Reviewer         │
                         │ Auto-Refactoring         │
                         │ BADC / ECACC             │
                         │ Harness                  │
                         └────────────┬─────────────┘
                                      │
                      production API / neutral contracts
                                      │
                 ┌────────────────────▼───────────────────┐
                 │ Optional neutral reusable libraries    │
                 │                                        │
                 │ repo_runtime                           │
                 │ process_runtime                        │
                 │ shared_contracts                       │
                 │ observability_contracts                │
                 │ content_hashing                        │
                 └────────────────────┬───────────────────┘
                                      ▲
                                      │
                    benchmark may also depend on these
                                      │
┌─────────────────────────────────────┴─────────────────────────────────┐
│                  e-ComGen/autonomous-dev-bench                       │
│                                                                       │
│  benchmark_core                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ Experiment DAG │ environments │ sandbox │ CAS │ evidence       │ │
│  │ worktrees      │ resources    │ replay  │ metrics │ provenance │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                    │                  │                    │            │
│            ┌───────▼──────┐   ┌──────▼─────┐    ┌────────▼──────┐    │
│            │ Corpus       │   │ Tasks      │    │ Mutation/Fault│    │
│            │ ProjectSpec  │   │ TaskSpec   │    │ libraries     │    │
│            └───────┬──────┘   └──────┬─────┘    └────────┬──────┘    │
│                    └─────────────────┬┴───────────────────┘           │
│                                      │                                │
│                     immutable Scenario / checkpoints                  │
│                                      │                                │
│       ┌──────────────┬───────────────┼──────────────┬─────────────┐   │
│       ▼              ▼               ▼              ▼             ▼   │
│ AutoRef Suite   AutoZoning      Architecture     Harness      FullSystem│
│   own oracle      own oracle      own oracle      own oracle    own oracle│
│       │              │               │              │             │   │
│       └──────────────┴───────────────┴──────────────┴─────────────┘   │
│                                      │                                │
│                       independent SuiteResult                         │
│                                      │                                │
│                     BenchmarkEvidenceBundle                           │
│                                      │                                │
│                     Result DB / reports / dashboard                   │
└───────────────────────────────────────────────────────────────────────┘

                     NO ARROW IS ALLOWED:

                  Production ───────► Benchmark
```

The benchmark repository should look approximately like this:

```text
e-ComGen/autonomous-dev-bench/
│
├── pyproject.toml
├── README.md
├── benchmark.lock
│
├── packages/
│   └── benchmark_core/
│       └── benchmark_core/
│           ├── experiment.py
│           ├── identity.py
│           ├── project.py
│           ├── task.py
│           ├── scenario.py
│           ├── environment.py
│           ├── checkout.py
│           ├── worktree.py
│           ├── execution.py
│           ├── isolation.py
│           ├── dag.py
│           ├── cache.py
│           ├── evidence.py
│           ├── provenance.py
│           ├── metrics.py
│           ├── replay.py
│           ├── coverage.py
│           └── result.py
│
├── corpus/
│   ├── projects/
│   │   ├── httpx.yaml
│   │   ├── anyio.yaml
│   │   ├── pytest.yaml
│   │   └── ...
│   ├── baselines/
│   └── adapters/
│
├── tasks/
│   ├── httpx/
│   ├── pytest/
│   ├── sqlalchemy/
│   └── ...
│
├── mutations/
│   ├── structural/
│   ├── architecture/
│   ├── ownership/
│   ├── contracts/
│   └── metamorphic/
│
├── faults/
│   ├── process/
│   ├── filesystem/
│   ├── tool/
│   ├── concurrency/
│   ├── cache/
│   └── versioning/
│
├── suites/
│   ├── auto_refactoring/
│   ├── auto_zoning/
│   ├── architecture_assurance/
│   ├── architecture_governance/
│   ├── zone_development/
│   ├── badc/
│   ├── ecacc/
│   ├── task_owner/
│   ├── harness/
│   └── full_system/
│
├── scenarios/
│   ├── real_world/
│   ├── historical/
│   ├── synthetic/
│   └── generated/
│
├── reference_projects/
│   └── benchmark_selftest_project/
│
├── reports/
├── cli/
└── tests/
    ├── core/
    ├── cache/
    ├── firewall/
    ├── isolation/
    └── mutation_verification/
```

A separate private store/repository should contain unreleased evaluation material:

```text
autonomous-dev-bench-private/
    hidden_project_pins/
    hidden_task_overlays/
    hidden_mutation_instances/
    hidden_oracle_labels/
    hidden_seeds/
    campaign_manifests/
```

It need not contain copies of every public repository. Keeping the **task overlay, concrete mutation instance, seed and oracle private is much more valuable than pretending the identity of `httpx` is secret**. OpenAI explicitly notes that static benchmarks built from public GitHub repositories are likely to be contaminated in foundation-model pretraining. citeturn18view0 LiveCodeBench's continuous collection strategy is one response to precisely this contamination problem, while newer repository-level work also shows that prompt construction itself can reveal solution structure and therefore must be considered part of benchmark methodology. citeturn7view4turn7view1

**Utility ownership should be explicit:**

| Utility | Ownership |
|---|---|
| `InjectedSmellMutation` | `BENCHMARK_ONLY` |
| hidden corpus / expected labels | `BENCHMARK_ONLY` |
| suite oracle composition | `BENCHMARK_ONLY` |
| contamination ledger | `BENCHMARK_ONLY` |
| benchmark coverage planner | `BENCHMARK_ONLY` |
| `RepositorySnapshot` | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| content hashing | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| worktree manager | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| generic subprocess/resource runner | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| CAS/artifact primitives | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| neutral `EvidenceRef` | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| neutral `SnapshotFingerprint` | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| trace/correlation identifiers | `GENERIC_INFRASTRUCTURE_REUSABLE` |
| zone authority policy | `PRODUCTION_CORE` |
| TaskOwner policy | `PRODUCTION_CORE` |
| CandidateSnapshot semantics | `PRODUCTION_CORE` |
| actual repair/refactoring algorithm | `PRODUCTION_CORE` |

The benchmark must not own production contracts merely because it consumes them. A small `shared_contracts` package may own neutral objects such as:

```text
EvidenceRef
SnapshotFingerprint
CandidateId
CorrelationId
ArtifactDigest
```

Production can emit them and the benchmark can verify them independently.

For tracing, the same rule applies: do **not** add `BenchmarkTraceEvent` to every production component. Emit a normal structured observability stream. OpenTelemetry's trace model already provides spans with parentage, timestamps, attributes, events, links and status, which is enough to represent stage correlation without teaching production code about benchmark concepts. citeturn2search1turn2search5 The benchmark translates those normal events into `StageResult` evidence.

**The suite interface should be narrower than the proposed `prepare/run/observe/evaluate/collect_evidence`.** Checkout, isolation and evidence collection belong to the platform, not the capability suite.

A better design is:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SuitePlan:
    suite_id: str
    input_checkpoint: str
    adapter_id: str
    oracle_ids: tuple[str, ...]
    required_observations: tuple[str, ...]
    hard_gate_ids: tuple[str, ...]


@dataclass(frozen=True)
class SystemObservation:
    status: str
    output_artifact: str | None
    trace_artifact: str | None
    changed_tree_digest: str | None
    metrics_artifact: str | None


@dataclass(frozen=True)
class OracleResult:
    oracle_id: str
    status: str
    measurements: dict[str, object]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    status: str
    oracle_results: tuple[OracleResult, ...]
    hard_gate_failures: tuple[str, ...]


class BenchmarkSuite(Protocol):
    def plan(self, scenario) -> SuitePlan:
        ...

    def evaluate(
        self,
        scenario,
        observation: SystemObservation,
        oracle_context,
    ) -> SuiteResult:
        ...


class SystemAdapter(Protocol):
    def invoke(self, invocation, run_context) -> SystemObservation:
        ...


class MutationRecipe(Protocol):
    def apply(self, workspace, parameters):
        ...

    def verifyApplied(self, before_snapshot, after_snapshot, parameters):
        ...


class FaultInjector(Protocol):
    def arm(self, execution_context, fault_spec):
        ...

    def verifyTriggered(self, evidence, fault_spec):
        ...
```

The important dependency is:

```text
ExperimentRunner
    owns prepare/isolate/execute/capture

BenchmarkSuite
    owns capability experiment plan + interpretation

SystemAdapter
    owns invocation of normal production API

Oracle
    owns independent evaluation

Production system
    knows none of these benchmark concepts
```

That makes `if benchmark_mode:` an architectural violation.

A suite may register capabilities, but it cannot override checkout internals or CAS behaviour. A project may have an adapter, but it cannot override oracle semantics.

The common Scenario language should likewise remain intentionally small. **Use declarative manifests for identities and composition; Python for behavioural machinery.** Do not invent a general-purpose YAML programming language.

Good:

```yaml
scenario_id: httpx.add_transport.bad_duplicate_dispatch

project: httpx.pinned_001
task: httpx.add_transport_provider

checkpoint: candidate_bad_dispatch

mutations:
  - id: duplicate_provider_dispatch
    seed: 819283

faults: []

execution:
  mode: fresh_process

suites:
  - auto_zoning
  - auto_refactoring
```

Bad:

```yaml
expectations:
  auto_refactoring:
    when:
      expression:
        if:
          ...
```

The **scenario should not contain the expected answer**. Suite manifests, preferably private when appropriate, bind the scenario to capability-specific oracles.

The runner API can remain simple:

```python
result = runner.run(
    project="httpx.pinned_001",
    suite="auto_refactoring",
    scenario="httpx.add_transport.bad_duplicate_dispatch",
)

pipeline_result = runner.run_pipeline(
    task="httpx.add_transport_provider",
    suites=(
        "auto_zoning",
        "architecture_assurance",
        "zone_development",
        "auto_refactoring",
    ),
)
```

`pytest` remains excellent for `benchmark_core`'s own unit/integration tests and has a deliberate extensible hook/plugin architecture, but it should not become the benchmark's data model or historical experiment database. citeturn12search16turn17search35 The primary abstraction should be `Experiment`, not “10,000 pytest functions”.

## Corpus, tasks, contamination and workload design

The corpus should have **two orthogonal axes**:

```text
ProjectCorpus
    "what repository state exists?"

TaskCorpus
    "what autonomous development request must be handled?"
```

A repository scan benchmark can use only the first. TaskOwner, Zoning, Architecture, Coder and full-system evaluation need both.

A sufficiently complete `ProjectSpec` should look like:

```yaml
benchmark_spec_version: "1.0"

project:
  project_id: "httpx.pinned_001"

  source:
    repository: "encode/httpx"
    commit_sha: "<full-immutable-sha>"
    source_tree_digest: "sha256:<digest>"

  legal:
    license_spdx: "<verified-at-onboarding>"
    license_file_digest: "sha256:<digest>"

  platforms:
    operating_systems:
      - linux
      - windows

    python:
      - "3.11"
      - "3.12"

  bootstrap:
    adapter_id: "python-standard-v1"
    dependency_spec_digests:
      - "sha256:<digest>"

    extras:
      - tests

    install:
      command_id: "project-install-v1"

  baseline:
    commands:
      - id: unit-tests
        argv: ["python", "-m", "pytest"]
        timeout_seconds: 1200

    required_status: passing
    baseline_health_revision: "1"

  classification:
    scale: medium
    domain:
      - http-client
      - networking

    architecture_features:
      - async
      - sync
      - transports
      - public-api

    dynamic_features:
      - runtime-dispatch
      - async-runtime

    capabilities_exercised:
      - auto_refactoring
      - auto_zoning
      - architecture_assurance
      - zone_development
      - harness
      - full_system

  security:
    build_network_policy: package_indices_only
    execution_network_policy: none

  corpus:
    release: "2026.1"
    partition: validation
```

No `latest` is permitted. Corpus identity includes repository + full commit SHA + dependency material, and semantic changes to a corpus item produce a new identity.

A `TaskSpec` is independently versioned:

```yaml
task_id: "httpx.add_transport_provider.v1"

project_id: "httpx.pinned_001"

baseline_checkpoint: "baseline"

user_request: >
  Add a selectable transport provider that conforms to the
  existing transport contract and works through the public client API.

expected_scope:
  affected_domains:
    - client_configuration
    - transport

  candidate_zones:
    - transport_ownership
    - client_integration

cross_zone_contracts:
  - contract_id: transport_provider_contract
    producer_zone: transport_ownership
    consumer_zone: client_integration

functional_oracle_ref:
  id: hidden.httpx.transport.feature.v1

architecture_constraints:
  acceptable_families:
    - existing_transport_abstraction
    - compatible_factory_indirection

  forbidden:
    - hidden_process_global_registry
    - duplicated_provider_dispatch
    - unauthorized_cross_zone_state
```

Crucially, the benchmark does not hand this whole record to every system. It constructs projections:

```text
TaskOwnerView
    user_request

AutoZoningView
    user_request
    source snapshot

ArchitectureAssuranceView
    source snapshot
    zoning proposal
    architecture proposal

CoderView
    user request
    approved zones/contracts

AutoRefactoringView
    resulting candidate snapshot

OracleView
    EVERYTHING REQUIRED FOR EVALUATION,
    including hidden expectations
```

That prevents accidental leakage through shared TaskSpec reuse.

### Contamination policy

A project should **not** be treated as one binary `hidden/not-hidden` object. Public GitHub identity is too weak a secrecy boundary for LLM agents; OpenAI explicitly identifies likely contamination in benchmarks derived from public GitHub repositories. citeturn18view0 Continuous/fresh benchmark construction and temporal cutoffs are increasingly used to mitigate this, and recent repository-level research warns that even the wording of a task can leak information about the future solution. citeturn7view4turn7view1

Track exposure separately for:

```text
repository identity
repository source snapshot
task family
exact TaskSpec
mutation family
concrete mutation instance
metamorphic transformation seed
fault scenario
expected architecture constraints
oracle implementation
oracle labels
historical future commit / PR
```

The practical policy should be:

| Exposure | Consequence |
|---|---|
| Team/system has seen `httpx` source | Mark `PROJECT_SEEN`; **does not invalidate every future httpx scenario** |
| Auto-Refactoring was tuned on one httpx mutation | That concrete experiment is contaminated for Auto-Refactoring |
| Exact shared TaskSpec was used for tuning a common agent | Treat task as contaminated for **all capability evaluations reached by that tuned agent** |
| Mutation *family* is public, concrete randomized instance is private | Valid as unseen-instance/generalization evaluation, but not as unseen-concept evaluation |
| Exact mutation instance and expected response were exposed | Not hidden |
| Hidden oracle/expected output leaked | **Globally invalidate that evaluation instance** |
| Public project, private task overlay + private mutation seed + private oracle | Recommended default hidden regime |
| Future PR/solution text was accessible to evaluation agent | Historical scenario is contaminated |

So the answer to:

> If `attrs` was used for Auto-Refactoring validation, can it later be hidden for Auto-Zoning?

is:

**The repository identity cannot honestly be called unseen, but a new Auto-Zoning task/mutation/oracle on the same pinned or transformed repository can still be a valid hidden scenario.**

Record it as something such as:

```text
project_exposure       = SEEN
task_exposure          = UNSEEN
mutation_instance      = UNSEEN
oracle                 = PRIVATE
expected_labels        = PRIVATE
```

This is more informative than either global contamination or purely suite-local contamination.

However, if Auto-Refactoring tuning exposed the **same task's semantic decomposition** that Auto-Zoning will later be asked to produce, contamination propagates across suites because the leaked information is capability-relevant.

The firewall should enforce this mechanically:

```text
production package cannot import benchmark package

hidden manifests live outside developer checkout

hidden oracle data is not mounted into SUT sandbox

agent receives only its scenario projection

benchmark IDs are removed from semantic prompts

mutation parameter names are not exposed

random symbol renaming/layout transformations are supported

future historical commits/PR text are blocked

scenario seed is stored only in benchmark evidence

network access is policy-controlled

model/tool web access is explicitly recorded

all exposed artifacts enter contamination ledger
```

“Poisoning” fixture names and comments can be useful as a robustness test, but the deeper defence is **semantic randomization**: the model should not succeed because every mutable-global mutation contains a variable called `GLOBAL_STATE`.

### Real-project portfolio

The original set is a good **shared Python foundation**, but not every project should have equal weight in every suite. HTTPX's documented sync/async API and transport abstractions, Requests' transport adapters, Flask's blueprints/extensions, Click's command/context hierarchy, and attrs' validators/converters already offer materially different architectural shapes. citeturn11search12turn15search24turn16search0turn16search4turn16search2turn16search6 AnyIO adds structured asynchronous task/cancellation/networking behaviour; pytest and pluggy provide rich hook/plugin boundaries; Pydantic has distinct validation/serialization concerns and a separate core implementation. citeturn11search1turn11search21turn12search16turn12search1turn12search2 Tenacity is particularly useful for retry/lifecycle behaviour, while Cookiecutter provides filesystem/template/hook workloads. citeturn20search0turn20search6turn20search18

The following is an **architectural suitability assessment**, not a claim that every cell has an existing ready-made benchmark:

| Project | Refactor | Zoning | Architecture | Zone Dev | Harness | Full system |
|---|---:|---:|---:|---:|---:|---:|
| `requests` | High | Medium | Medium | Medium | Medium | Medium |
| `flask` | High | High | High | High | Medium | High |
| `click` | Medium | Medium | Medium | Medium | High | Medium |
| `attrs` | High | Low | Medium | Low | Medium | Low–Medium |
| `pydantic` | High | High | High | High | Medium | High |
| `pytest` | High | High | High | High | High | High |
| `httpx` | **High** | **High** | **High** | **High** | **High** | **High** |
| `tenacity` | Medium–High | Low | Medium | Medium | **High** | Medium |
| `pluggy` | High | Medium | **High** | **High** | **High** | Medium |
| `anyio` | Medium | Medium | High | High | **High** | **High** |
| `cookiecutter` | Medium | Medium | Medium | Medium | High | Medium–High |
| `tox` | Medium | Medium | Medium | Medium | **High** | Medium |

For zoning, the set should be deliberately expanded. Strong candidates include:

**SQLAlchemy** because Core and ORM are distinct layers and the project supports multiple dialects/backends; that gives natural provider/consumer and boundary tasks. citeturn4search1turn4search5turn4search21

**Django** because the application registry, models, authentication and admin mechanisms provide multiple substantial responsibilities and cross-application integration surfaces. citeturn4search20turn4search12turn4search4

**Scrapy** because its documented engine, downloader middleware, spider middleware, extensions and item pipeline expose multiple execution and responsibility boundaries. citeturn4search2turn4search6turn4search34

**Jupyter Server** because server extensions and service-oriented internal structure create natural plugin/ownership scenarios. citeturn4search3turn4search7turn4search15

**Celery** is especially valuable for orchestration, retries, acknowledgements, distributed-state and crash semantics, but should be a Linux-focused specialist corpus item rather than a cross-platform baseline because Celery's own documentation does not support Microsoft Windows. citeturn3search34turn3search6turn3search22

Useful constructed task families include:

```text
HTTPX
    Add transport/provider
    Change transport configuration contract
    Extend sync/async behaviour consistently

pytest / pluggy
    Introduce a new hook specification
    Add provider + consumer of a hook
    Change plugin lifecycle contract

SQLAlchemy
    Add dialect-specific feature requiring Core contract changes
    Extend type/compiler behaviour across provider boundary

Django
    Introduce model-field behaviour spanning ORM and integration layer
    Extend application-level registration behaviour

Scrapy
    Add handler/middleware provider
    Extend configuration consumed by multiple pipeline stages

Jupyter Server
    Add extension capability plus route/service integration

Celery
    Add backend/transport behaviour
    Change acknowledgement/retry lifecycle
```

Each should preferably have **multiple acceptable implementation families**, not a single golden diff.

Real repositories have no unique architectural truth. Ground truth should therefore be assembled from several evidence sources:

```text
injected controlled defect
existing contract and tests
task constraints
historical accepted design
negative/forbidden architecture rules
expert labels
synthetic semantic model
independent behavioural comparison
```

A historical post-refactor commit is a **witness of an accepted solution**, not proof that all alternatives are wrong.

Git history is still extremely valuable. RefactoringMiner demonstrates that refactorings and AST-level changes can be mined from commit history, making “before → after” candidate discovery practical. citeturn14search0turn14search4 For benchmark construction, use historical mining as:

```text
T0 repository state
    ↓
issue/task reconstructed without future discussion
    ↓
candidate historical change in (T0, T1]
    ↓
tests + invariants + expert adjudication
    ↓
historical benchmark instance
```

Do not expose the future PR text, commit message or solution discussion to the agent. Time-consistent repository benchmarking research specifically shows why future information and prompt framing need to be controlled. citeturn7view1

### Synthetic and metamorphic corpora

A shared generator library has high long-term ROI, especially for Auto-Zoning:

```text
ResponsibilityGraph
    nodes:
        responsibilities
        providers
        consumers
        stores
        contracts

    edges:
        owns
        calls
        depends_on
        publishes
        reads
        writes

    constraints:
        allowed_cross_zone_edges
        forbidden_edges
        ownership

                ↓

          SourceRealizer

                ↓

packages / modules / classes / functions
```

Ground truth then originates in a semantic graph rather than being reverse-engineered from generated source.

Do **not** start by building a general Python-program synthesizer. Start with parameterized architectural templates:

```text
ProviderFamilyGenerator
PluginArchitectureGenerator
LayeredApplicationGenerator
StateMachineGenerator
CrossZoneProjectGenerator
SharedMutableStateGenerator
```

with dimensions such as:

```text
seed
zone_count
provider_count
dependency_density
cross_zone_edge_count
shared_state_probability
module_layout
symbol_vocabulary
dispatch_style
```

Then compose metamorphic transformations:

```text
RenameSymbols
MoveFile
EquivalentSyntax
ReorderDefinitions
ChangePackageLayout
CommentPoisoning
DeadCodeInjection
Formatting
AliasIntroduction
```

Randomized testing and metamorphic/equivalence-oriented testing have a strong precedent in compiler verification: Csmith generates random programs and uses differential execution, while equivalence-modulo-input techniques construct transformations whose relevant behaviour should remain equivalent. citeturn5search33turn5search18 Stateful property testing is similarly valuable for lifecycle systems; Hypothesis explicitly supports model-based state-machine testing through sequences of operations against a real system and a model. citeturn7view9

That makes a generic:

```python
class StatefulScenarioMachine:
    def actions(self):
        ...

    def invariants(self):
        ...

    def observations(self):
        ...
```

a promising **post-MVP** platform primitive for:

```text
AutoRefactoring:
    edit → analyze → transform → restart → analyze

Zone runtime:
    dispatch → update dependency → crash → resume → commit

Harness:
    launch → timeout → retry → duplicate result → restart

ECACC:
    receive candidate → stale dependency → revalidate → accept/reject
```

## Execution, environments, caching, isolation and coverage

The execution architecture should resemble a small build system:

```text
ProjectSource
      │
      ▼
RepositoryMaterialization
      │
      ├─────────────► source digest
      ▼
EnvironmentResolution
      │
      ▼
BaselineExecution
      │
      ├─────────────► baseline evidence
      │
      ├─────────────► suite worktree A
      │                   ▼
      │               mutation A
      │                   ▼
      │              AutoRefactoring
      │
      ├─────────────► suite worktree B
      │                   ▼
      │               task overlay
      │                   ▼
      │                AutoZoning
      │
      └─────────────► suite worktree C
                          ▼
                     FullSystem
```

This is a good fit for content-addressed execution. Bazel's remote-cache design is a useful architectural model: actions explicitly declare inputs, commands, environment and outputs; action results are addressed by action hashes while artifacts live in a content-addressable store. citeturn19view0 The benchmark does not need Bazel itself, but should borrow the invariant:

> **A cached result is valid only if every behaviour-relevant input is represented in its cache key.**

That is particularly important because real benchmark harnesses can get this wrong. The current SWE-bench harness documentation warns about cached evaluation results being associated with run/instance identity rather than arbitrary changed patch contents, illustrating why an autonomous-development benchmark should never use a human-friendly experiment ID as a correctness cache key. citeturn8search3

### Repository and worktree cache

Recommended structure:

```text
cache/
    git/
        <repository-key>/
            anchor.git / object database

    environments/
        <environment-fingerprint>/

    baseline/
        <baseline-action-key>/

    cas/
        sha256/
            ab/
              <digest>

runs/
    <run-id>/
        worktree/
        temp/
        outputs/
```

Use:

```text
immutable source commit
        ↓
shared Git objects
        ↓
fresh linked/ephemeral worktree
        ↓
TaskOverlay
        ↓
MutationOverlay
        ↓
suite execution
        ↓
destroy worktree
```

Git explicitly supports multiple linked worktrees sharing one repository and describes detached throwaway worktrees as convenient for experimental changes and testing. citeturn19view1 This provides a strong cross-platform baseline without depending on OverlayFS.

`reflink` or copy-on-write filesystem snapshots can be optional accelerators on supporting filesystems. Overlay filesystem techniques may be used on Linux, but **benchmark correctness must not require them**. On Windows, default to Git worktrees or ordinary copies for repositories that do not tolerate worktree arrangements.

### Environment fingerprint

Do not define an environment merely as:

```text
Python 3.12
```

Use a canonical record:

```yaml
environment_fingerprint:
  project_source_digest: "sha256:..."
  repository_commit: "<sha>"

  platform:
    os_family: linux
    os_version: "<recorded>"
    architecture: x86_64

  interpreter:
    implementation: CPython
    version: "3.12.x"
    executable_digest: "sha256:..."

  dependencies:
    lock_digest: "sha256:..."
    extras:
      - tests

  installer:
    name: uv
    version: "<recorded>"

  system_dependencies:
    image_or_manifest_digest: "sha256:..."

  project_adapter:
    id: python-standard
    version: "3"

  environment:
    relevant_variables:
      LANG: "..."
      TZ: "UTC"
      PYTHONHASHSEED: "..."

  policy:
    build_network: package_indices_only
    run_network: none

  bootstrap_spec_digest: "sha256:..."
```

Then:

```text
EnvironmentCacheKey =
    sha256(canonical_json(EnvironmentFingerprint))
```

`uv` is a reasonable default dependency manager for the Python corpus because its official documentation supports Linux, Windows and macOS, provides a global dependency cache, and supports lockfile/project management. Its cache configuration can also account for files, Git commit information and environment variables. citeturn19view3turn19view4

However, **the benchmark's own EnvironmentFingerprint remains authoritative**. Do not assume a package manager's internal cache keys cover every benchmark-relevant dimension.

The caching hierarchy should be:

```text
Level                 Key

Git objects            repository identity + fetched object identity

Source snapshot        repository + full SHA + tree digest

Dependency downloads   installer-native content identity

Environment artifact   EnvironmentFingerprint

Baseline result        EnvironmentFingerprint
                     + baseline command-spec hash
                     + benchmark executor version
                     + test policy version

Benchmark-side AST     source-tree digest
                     + analysis-tool version
                     + analysis config

Suite observation      ALL OF:
                       input checkpoint digest
                       system commit
                       system config
                       adapter version
                       model/provider where applicable
                       prompt/policy version
                       tools
                       seed
                       execution mode

Oracle result          observation digest
                     + oracle version
                     + policy version
```

**Evidence reuse policy:**

| Evidence | Cross-suite reuse? |
|---|---|
| Git repository objects | Yes |
| immutable checkout | Yes as source, but each run gets isolated writable worktree |
| package download/wheel cache | Yes |
| exact environment artifact | Yes |
| baseline test result | **Yes**, exact fingerprint only |
| test collection metadata | Yes, exact project/environment/tool key |
| source hashes | Yes |
| benchmark-side syntactic AST facts | Yes, exact parser/config version |
| generic dependency graph used only for scheduling | Potentially yes |
| Auto-Zoning semantic interpretation | **No** |
| Auto-Refactoring analysis/certificate | **No** |
| architecture judgement | **No** |
| LLM answer from another suite | **No by default** |
| SUT-produced “safe” certificate | May be stored, **never reused as benchmark truth** |

This is the critical distinction between:

```text
SAFE SHARED FACT
    file X imports Y

UNSAFE SHARED INTERPRETATION
    therefore responsibility belongs to Zone Z
```

The benchmark platform must **not become a shared semantic frontend consumed by production systems**. If multiple production components genuinely need an AST, dependency graph or call graph, build a separate neutral `program_analysis` package. Production and benchmark can both depend on it where appropriate, although high-assurance benchmark oracles should sometimes use an independent implementation to avoid common-mode errors.

### Baseline health and failure semantics

Each project/environment tuple gets a baseline registry entry:

```text
BaselineHealth:
    project_digest
    environment_fingerprint
    command_spec
    last_verified_at
    result
    evidence_digest
```

Run outcomes must distinguish:

```text
PASS

FAIL
    SUT behaved incorrectly

INFRA_FAILURE
    benchmark runtime/cache/host failed

BASELINE_BROKEN
    target repository was not healthy before experiment

UNSUPPORTED
    declared environment/platform unsupported

SKIPPED
    campaign intentionally omitted experiment

INVALID_EXPERIMENT
    mutation/precondition/oracle could not be established
```

A mutation that silently failed to apply is **not** evidence that a system correctly handled it.

### Cache verification

The benchmark cache itself is part of the trusted computing base. Therefore perform:

```text
periodic random fresh recomputation

cache-hit result
        ==
fresh result
```

for deterministic actions.

Also test:

```text
changed source → miss
changed env var → miss
changed dependency lock → miss
changed oracle version → oracle miss
changed SUT commit → observation miss
changed patch → observation miss
same friendly task ID but changed content → miss
corrupted CAS object → detected by digest
```

### Fault and process isolation

Runs should explicitly support:

```text
SAME_PROCESS
FRESH_PROCESS
RESTART_PROCESS
```

The default authoritative mode should be:

```text
fresh process
fresh writable worktree
fresh run temp directory
immutable external caches
```

Faults are applied at realistic boundaries:

```text
PROCESS_CRASH
    externally terminate process

FILE_WRITE_FAILURE
PERMISSION_DENIED
DISK_FULL
PARTIAL_WRITE
    filesystem/OS fault boundary

NETWORK_TIMEOUT
TOOL_TIMEOUT
    proxy/executor boundary

DUPLICATE_RESULT
STALE_RESULT
LOST_ACK
    protocol/control-plane boundary

CONCURRENT_CHANGE
DEPENDENCY_CHANGED
ARCHITECTURE_CHANGED
    external-state evolution scenario

CORRUPTED_CACHE
    cache boundary
```

`DEPENDENCY_CHANGED` and `ARCHITECTURE_CHANGED` are better understood as **environment/state evolution scenarios** than primitive machine faults, but they can live in the same scenario catalogue.

Do not add benchmark-only production hooks merely to inject these. Prefer process termination, network proxies, filesystem permissions, controlled tool endpoints and normal dependency injection points that have legitimate production use.

Public repositories must be treated as untrusted code. Linux authoritative runs can use containers with explicit CPU/memory limits, disabled networking during execution, seccomp/rootless configurations where appropriate; Docker's own documentation provides controls for resource constraints, `none` networking, rootless mode and syscall filtering. citeturn10search0turn10search5turn10search2turn10search3 But control of a Docker daemon is itself security-sensitive, so containers should not be confused with an infallible security boundary. citeturn10search6

For high-trust hidden campaigns, especially across Linux and Windows, prefer disposable VM/CI workers with:

```text
no production credentials
ephemeral filesystem
restricted network
resource quotas
process-tree termination
artifact-only egress
```

Windows remains a first-class target. Git itself is actively available on Windows, while Windows has platform-specific case sensitivity and long-path behaviour that can expose defects hidden on Linux. citeturn13search27turn1search6turn1search13 Therefore `OS` is a benchmark dimension, not merely CI infrastructure metadata.

### Avoiding combinatorial explosion

Your example:

```text
12 projects
× 10 systems
× 30 scenarios
× 4 Python versions
× 2 OS
= 28,800 experiment combinations
```

before model repeats or fault variants.

Do not execute that Cartesian product.

Every experiment should advertise a coverage vector:

```text
project
suite
capability
mutation family
fault family
OS
Python
execution mode
positive / negative / unknown
authority path
restart path
cross-zone path
model class
```

The campaign planner then selects a minimal/risk-weighted set.

Use three mechanisms together:

```text
Changed-component selection
        +
covering-array / pairwise interaction coverage
        +
explicit high-risk scenarios
```

NIST's combinatorial-testing work supports t-way/covering-array testing specifically as a way of covering important parameter interactions with dramatically fewer tests than exhaustive Cartesian products. citeturn13search1turn13search21 It should supplement—not replace—known critical crash, authorization and false-safe scenarios.

A practical planner can formulate experiments as set cover:

```text
Universe:
    required coverage obligations

CandidateExperiment:
    covers {obligation A, B, C, ...}
    estimated_cost
    risk_weight

Objective:
    cover all mandatory obligations
    minimize estimated cost
    maximize risk-weighted secondary coverage
```

Start with a greedy set-cover heuristic; there is no need for a sophisticated optimizer in v1.

## Mutation, oracle, evidence and metric architecture

The most important abstraction here is:

```text
MUTATION
    describes what world was created

ORACLE
    describes what one capability must demonstrate in that world
```

They are not the same object.

A shared mutation specification should resemble:

```python
@dataclass(frozen=True)
class MutationDescriptor:
    mutation_id: str
    category: str
    semantic_intent: str

    applicable_project_tags: tuple[str, ...]
    precondition_ids: tuple[str, ...]

    supported_suite_ids: tuple[str, ...]

    reversible: bool
    deterministic_from_seed: bool

    preserved_properties: tuple[str, ...]
    intentionally_changed_properties: tuple[str, ...]
```

Concrete execution:

```text
MutationDescriptor
        │
        ▼
MutationRecipe.apply()
        │
        ▼
before tree ─────► after tree
        │             │
        └─────► verify_applied()
                      │
                      ▼
             MutationApplicationEvidence
```

For example:

```text
INTRODUCE_MUTABLE_GLOBAL
```

contains:

```text
semantic_intent:
    introduce state whose lifetime/ownership is broader
    than the original local responsibility

preserved:
    functional baseline behaviour at injection time

changed:
    ownership/state topology
```

It should **not** contain:

```text
expected_answer = "extract StateManager"
```

The binding belongs to suites:

```text
AutoRefactoring:
    detect unsafe mutable-global design opportunity
    OR correctly KEEP_CURRENT in negative controls

AutoZoning:
    recognize widened ownership relationship where relevant

ArchitectureAssurance:
    reject a proposal if it introduces prohibited hidden attempt-global state

BADC:
    route specific violation evidence into repair

ECACC:
    reject candidate when independent policy violation persists
```

That same pattern applies to:

```text
DUPLICATE_PROVIDER_DISPATCH
SCATTER_CONSTRUCTION
INTRODUCE_INHERITANCE_FOR_REUSE
DUPLICATE_STATE_SWITCH
BREAK_PUBLIC_CONTRACT
MOVE_OWNER_ACROSS_BOUNDARY
CREATE_CROSS_ZONE_DEPENDENCY
INTRODUCE_IMPORT_CYCLE
CREATE_STALE_CONTRACT
REMOVE_REQUIRED_VERIFICATION
```

A mutation catalogue therefore shares **mechanism and semantic description, not verdict**.

### Oracle architecture

Reusable oracle primitives are desirable:

```text
FunctionalOracle
    run tests / explicit properties

DifferentialOracle
    compare baseline/candidate observable behaviour

PublicApiOracle
    compare exported names/signatures/contracts

FilesystemOracle
    compare permitted filesystem effects

TraceOracle
    compare events/state transitions

ArchitectureOracle
    check independently defined architecture constraints

OwnershipOracle
    compare zone/responsibility assignment with benchmark labels

AuthorityOracle
    validate writes/actions against authority policy

ContractOracle
    validate cross-component schemas

ConvergenceOracle
    check eventual stable result after retries/restarts

RecoveryOracle
    crash → recover invariants

PerformanceOracle
    latency/cost/resource constraints
```

But a suite owns the composition:

```text
AutoRefactoringOracleV4 =
    mutation_detection
    + semantic_preservation
    + public_api
    + false_safe_gate

AutoZoningOracleV3 =
    ownership_ground_truth
    + allowed_boundary_matrix
    + cross_zone_contract_labels

HarnessOracleV5 =
    event_sequence
    + duplicate_side_effect_detector
    + resource_budget
    + recovery_invariant
```

The benchmark must never ask the system:

```text
"Did you preserve semantics?"
```

and accept:

```text
certificate.safe = true
```

as its oracle.

SWE-bench's use of independent `FAIL_TO_PASS` and `PASS_TO_PASS` tests is a useful basic example of evaluation-side evidence rather than self-certification. citeturn18view0 For autonomous refactoring, expand this concept with:

```text
original project tests
new benchmark-side tests
differential execution
public API comparison
trace comparison
filesystem effects
serialization probes
object identity/lifetime probes
metamorphic executions
```

Likewise, Auto-Zoning must be evaluated against injected responsibility graphs, independent human labels, constrained synthetic ground truth or historical boundaries—not its own confidence score.

### Common evidence model

Use a common outer envelope:

```yaml
benchmark_run:
  run_id: "br_..."
  experiment_id: "exp_..."

  versions:
    benchmark_spec: "1.0"
    benchmark_core: "<commit>"
    corpus: "2026.1"

  input:
    project:
      project_id: "httpx.pinned_001"
      source_digest: "sha256:..."

    task:
      task_id: "httpx.add_transport_provider.v1"
      task_digest: "sha256:..."

    checkpoint:
      digest: "sha256:..."

    environment:
      fingerprint: "sha256:..."

  system:
    component_commits:
      auto_zoning: "<sha>"
      auto_refactoring: "<sha>"
      harness: "<sha>"

    model:
      provider: "<recorded-or-null>"
      model_id: "<recorded-or-null>"
      configuration_digest: "sha256:..."

  scenario:
    scenario_id: "httpx.add_transport.bad_duplicate_dispatch"
    seed: 819283

    mutations:
      - mutation_id: duplicate_provider_dispatch
        application_evidence: "cas:sha256:..."

    faults: []

  stages:
    - component: auto_zoning
      input_digest: "sha256:..."
      output_digest: "sha256:..."
      status: pass
      evidence_refs:
        - "cas:sha256:..."

    - component: auto_refactoring
      input_digest: "sha256:..."
      output_digest: "sha256:..."
      status: pass
      evidence_refs:
        - "cas:sha256:..."

  suite_results:
    auto_zoning:
      suite_version: "3"
      oracle_version: "7"
      status: pass
      measurements:
        ownership_precision: 1.0
        ownership_recall: 1.0

    auto_refactoring:
      suite_version: "4"
      oracle_version: "11"
      status: pass
      measurements:
        detected_expected_issue: true
        semantic_preservation: true
        false_safe: false

  system_result:
    status: not_evaluated

  metrics:
    wall_time_ms: 0
    peak_memory_bytes: 0
    tool_calls: 0
    llm_calls: 0
    input_tokens: 0
    output_tokens: 0
    changed_files: 0
    baseline_test_time_ms: 0

  provenance:
    runner_host_fingerprint: "sha256:..."
    started_at: "<timestamp>"
    completed_at: "<timestamp>"
    evidence_root_digest: "sha256:..."
```

The bundle on disk:

```text
run/
├── manifest.json
├── environment.json
├── provenance.json
├── baseline/
│   ├── result.json
│   ├── stdout.txt
│   └── stderr.txt
├── overlays/
│   ├── task.json
│   ├── mutation.json
│   └── mutation.diff
├── system_outputs/
├── stages/
│   ├── auto_zoning.json
│   └── auto_refactoring.json
├── oracles/
│   ├── auto_zoning/
│   └── auto_refactoring/
├── metrics.json
├── certificate_checks.json
├── timeline.jsonl
├── diff.patch
├── replay.sh
└── replay.bat
```

This model follows the same fundamental idea as software provenance systems: preserve verifiable information describing **where, when and how an artifact was produced**, sufficient for later verification or reconstruction. SLSA's provenance model explicitly frames provenance in those terms and connects it to rebuildability and verification. citeturn19view2

A `StageResult` is essential for blame attribution:

```python
@dataclass(frozen=True)
class StageResult:
    component: str

    input_fingerprint: str
    output_fingerprint: str | None

    status: str

    started_at: str
    completed_at: str

    evidence_refs: tuple[str, ...]
    trace_refs: tuple[str, ...]

    failure_class: str | None
```

Then an E2E failure becomes:

```text
TaskOwner                  PASS
Auto-Zoning                PASS
Architecture Assurance     PASS
Coder                      PASS
Reviewer                   PASS
Auto-Refactoring           FAIL: FALSE_SAFE
ECACC                      FAIL-CLOSED
Integration                NOT_RUN
```

instead of:

```text
FULL_SYSTEM = FAIL
```

### Metrics, dashboard and result history

Use a namespaced registry:

```text
core.wall_time
core.cpu_time
core.peak_memory
core.disk_written
core.tool_calls
core.llm_calls
core.input_tokens
core.output_tokens
core.changed_files
core.test_time

auto_refactoring.precision
auto_refactoring.recall
auto_refactoring.false_safe
auto_refactoring.keep_current_accuracy

auto_zoning.responsibility_precision
auto_zoning.ownership_recall
auto_zoning.cross_zone_false_positive

architecture.false_admission
architecture.false_escalation

harness.restart_count
harness.retry_count
harness.duplicate_suppression
harness.time_to_completion
```

The dashboard can be shared, but its landing page should show:

```text
Release gates
Capability health
Regressions
Infrastructure health
Cost/latency
Corpus coverage
```

with drill-down per suite. It should never silently average incomparable quantities into one headline score.

For storage, the simplest progression is:

```text
MVP:
    filesystem/object CAS
    + SQLite metadata index
    + JSON canonical result

Later:
    Parquet export for longitudinal analytics
```

Reports can derive:

```text
JSON      canonical machine result
JUnit     CI integration
Markdown  PR/release summaries
HTML      interactive exploration
Parquet   historical analysis
```

Comparison across commits must operate only on compatible experiment slices:

```text
same project/input digest
same scenario
same environment policy
same suite version
same oracle version
same acceptance policy
same model stratum where model involved
```

Changing `CorpusVersion` does not erase old results, but a whole-corpus aggregate from version A is not directly comparable with a whole-corpus aggregate from B unless the exact common experiment subset is selected.

Recommended version identities:

```text
BenchmarkSpecVersion
BenchmarkCoreVersion
CorpusVersion
TaskVersion
MutationVersion
FaultVersion
SuiteVersion
OracleVersion
PolicyVersion
```

A result without these is not durable experimental evidence.

## Concrete shared HTTPX experiment

HTTPX is especially suitable for demonstrating the design because its public API supports synchronous and asynchronous operation and it has transport abstractions that create real provider/consumer responsibility questions. citeturn11search12

Consider one immutable project:

```text
Project:
    httpx@<pinned-sha>
```

and one shared task:

```text
Task:
    Add a selectable transport provider
    conforming to the existing transport API.
```

The benchmark scenario creates checkpoints:

```text
S0
immutable upstream baseline
        │
        ▼
S1
TaskOverlay:
"Add provider X"
        │
        ├───────────────────────────────► Auto-Zoning input
        │
        ▼
architecture/coder fixture
        │
        ▼
S2
candidate implementation
        │
        ▼
Mutation:
DUPLICATE_PROVIDER_DISPATCH
        │
        ▼
S3
candidate_bad_dispatch
        │
        ├───────────────────────────────► Auto-Refactoring input
        │
        ├───────────────────────────────► Reviewer input
        │
        └───────────────────────────────► Architecture Governance input
```

The injected implementation intentionally creates something structurally equivalent to:

```text
client construction path A:
    if provider == A:
        ...
    elif provider == B:
        ...
    elif provider == X:
        ...

client construction path B:
    if provider == A:
        ...
    elif provider == B:
        ...
    elif provider == X:
        ...
```

The mutation recipe's job is only to establish:

```text
duplicate dispatch decisions exist in two locations

feature behaviour is initially functional

provider X conforms to required behavioural fixture

mutation was actually applied
```

It does **not** say what each subsystem must conclude.

The capability projections differ.

**Auto-Zoning receives S1**, not the hidden post-coder mutation:

```text
Input:
    repository
    task request

Expected evidence:
    identify transport/provider responsibility
    identify client-integration responsibility
    identify contract between them

Negative evidence:
    do not assign unrelated ownership solely because
    files import client types
```

**Architecture Assurance receives the zoning result plus proposed architecture:**

```text
Accept:
    architectures compatible with existing transport contract

Reject:
    hidden process-global mutable registry
    unauthorized dependency inversion
    boundary-breaking proposal

Do not require:
    one exact class name
    one exact design pattern
```

**Auto-Refactoring receives S3:**

```text
Expected:
    identify duplicated dispatch/design pressure

Possible accepted remediation:
    compatible strategy/factory/function table
    reuse of existing abstraction
    another behaviourally equivalent design

Independent preservation:
    original tests
    feature tests
    differential behavioural probes
    public API checks

Critical:
    a false SAFE / KEEP_CURRENT certificate
    is evaluated independently
```

**Harness uses the same logical task but introduces a lifecycle fault:**

```text
Coder completes S2
        ↓
crash before result acknowledgement
        ↓
restart
        ↓
duplicate/stale result delivered
```

Expected Harness evidence:

```text
same logical task is resumed

candidate identity remains attributable

duplicate result does not cause duplicate integration

budgets remain enforceable

stage evidence is complete

no benchmark-specific code path was used
```

**FullSystem gets only S0 + user request**:

```text
User request
   ↓
TaskOwner
   ↓
Auto-Zoning
   ↓
Architecture
   ↓
Coder
   ↓
Reviewer
   ↓
Auto-Refactoring
   ↓
Verification / ECACC
   ↓
CandidateSnapshot
```

The full-system oracle asks whether the feature works, the candidate is admissible, mandatory authorities passed and no hard invariant was violated. It does **not** replace the capability-specific results.

A shared scenario manifest can therefore stay answer-free:

```yaml
scenario_id: "httpx.transport_provider.duplicate_dispatch.v1"

project:
  id: "httpx.pinned_001"

task:
  id: "httpx.add_transport_provider.v1"

checkpoints:
  baseline: "source"

  task_ready:
    parent: baseline
    overlays:
      - task:httpx.add_transport_provider.v1

  candidate_bad_dispatch:
    parent: task_ready
    overlays:
      - fixture:transport_provider_functional_candidate
      - mutation:duplicate_provider_dispatch

mutations:
  duplicate_provider_dispatch:
    mutation_id: "DUPLICATE_PROVIDER_DISPATCH"
    seed: 819283

execution:
  default_mode: fresh_process

resources:
  wall_time_seconds: 1200
  network: none
```

Then Auto-Refactoring owns:

```yaml
suite:
  suite_id: auto_refactoring
  suite_version: "4"

input:
  checkpoint: candidate_bad_dispatch

system_adapter:
  id: auto_refactoring.production_api.v2

required_oracles:
  - mutation_presence.independent.v1
  - design_opportunity.v3
  - functional_regression.v2
  - differential_behavior.v1
  - public_api.v2

hard_gates:
  - no_false_safe
  - semantic_preservation

mutation_expectations:
  DUPLICATE_PROVIDER_DISPATCH:
    expected_classification_ref:
      "private:auto_refactoring/duplicate_dispatch/v5"

metrics:
  - detection_precision
  - detection_recall
  - keep_current_accuracy
  - changed_files
  - wall_time
```

while Auto-Zoning owns:

```yaml
suite:
  suite_id: auto_zoning
  suite_version: "3"

input:
  checkpoint: task_ready

system_adapter:
  id: auto_zoning.production_api.v3

required_oracles:
  - responsibility_ground_truth.v4
  - ownership_ground_truth.v3
  - boundary_constraints.v2

ground_truth:
  responsibility_labels_ref:
    "private:auto_zoning/httpx_transport_task/v2"

  acceptable_zone_sets_ref:
    "private:auto_zoning/httpx_transport_task/acceptable/v2"

hard_gates:
  - no_unauthorized_owner_assignment

metrics:
  - responsibility_precision
  - responsibility_recall
  - ownership_accuracy
  - cross_zone_false_positive
```

This is the decisive demonstration that the shared-platform hypothesis works:

```text
SAME:
    repository objects
    source snapshot
    environment
    baseline tests
    TaskSpec
    scenario identity
    provenance format
    artifact storage
    resource runtime

RELATED:
    mutation library
    task overlays
    checkpoint DAG

DIFFERENT:
    input projection
    observation
    oracle
    labels
    hard gates
    metrics
    capability conclusion
```

The platform therefore achieves **reuse of workload without reuse of judgement**.

## CI, release campaigns, rollout, economics and maximum-ROI priorities

CI should be campaign-driven rather than “run everything on every change”.

A dependency selector should model:

```text
changed file/package
        ↓
affected production components
        ↓
affected contracts
        ↓
suites consuming those contracts
        ↓
mutations/faults referenced by suites
        ↓
minimal project/environment coverage
```

Recommended campaigns:

| Campaign | Purpose | Typical coverage |
|---|---|---|
| **PR** | fast regression feedback | changed suite + benchmark-core tests + synthetic cases + few real-project canaries |
| **Nightly** | broad capability regression | rotating real corpus, more OS/Python combinations, fuzz/stateful scenarios, stochastic repeats |
| **Release** | frozen reproducible qualification | all required release suites on fixed corpus/version matrix |
| **Hidden black-box** | anti-overfitting/generalization | private overlays/seeds/oracles on isolated CI |
| **Full-system milestone** | composition assurance | small number of expensive L4 workflows with fault/restart cases |

Examples:

```text
Change:
    auto_refactoring/**

PR executes:
    benchmark_core contract tests
    AutoRefactoring synthetic suite
    AutoRefactoring high-risk real-project slice
    mutations referenced by AutoRefactoring
    one restart scenario

Does not execute:
    complete Auto-Zoning corpus
    complete TaskOwner corpus
```

But:

```text
Change:
    benchmark_core/environment.py

PR executes:
    benchmark_core self-tests
    cache/fingerprint tests
    one canary experiment from every suite

Nightly:
    expanded all-suite cache/fresh comparison
```

Release requirements should be declared by production package:

```yaml
package: auto_refactoring

required_benchmark_suites:
  - auto_refactoring.synthetic
  - auto_refactoring.real_world
  - auto_refactoring.proof_kill
  - auto_refactoring.external_validation
  - auto_refactoring.restart
```

For stochastic LLM experiments, keep the two analytical dimensions separate:

```text
SYSTEM CORRECTNESS
    fixed model/scaffold condition
    compare component commits

AGENT CAPABILITY
    fixed system revision
    compare model/provider/scaffold
```

Do not report a model improvement as if Auto-Zoning itself became more correct.

### Corpus lifecycle

Recommended release rules:

```text
Corpus MAJOR
    existing scenario meaning changes
    canonical project pin is replaced
    old experiment may no longer be semantically equivalent

Corpus MINOR
    new immutable projects/tasks/scenarios added
    existing IDs unchanged

Corpus PATCH
    non-semantic metadata correction
```

Even after a minor addition, headline whole-corpus metrics should not be compared blindly. Compare the common immutable experiment set.

Onboarding:

```text
candidate repository
        ↓
license check
        ↓
security review
        ↓
select immutable commit
        ↓
establish dependency material
        ↓
Linux baseline
        ↓
Windows baseline where claimed
        ↓
repeatability runs
        ↓
ProjectSpec
        ↓
suite suitability review
        ↓
admission to development partition
        ↓
validation campaign
        ↓
possible promotion
```

External repositories requiring dozens of special benchmark patches are poor corpus candidates.

A `ProjectAdapter` is allowed only for unavoidable bootstrap differences:

```python
class ProjectAdapter(Protocol):
    def resolveBootstrap(self, project):
        ...

    def baselineCommands(self, project):
        ...

    def prepareRuntimeEnvironment(self, context):
        ...
```

It must not contain:

```python
if project_id == "pytest":
    expected_architecture = ...
```

Project-specific **setup** is reasonable; project-specific hidden conclusions belong in suites/oracles.

### Regression promotion

Every discovered failure should enter a funnel:

```text
production failure / hidden failure / fuzz failure
                    ↓
              reproduce exactly
                    ↓
               minimize
                    ↓
        classify root semantic property
             ╱                  ╲
            ╱                    ╲
small synthetic regression     pinned real scenario
            ╲                    ╱
             ╲                  ╱
                 permanent tier
```

Automatic delta debugging has potentially high value for fuzz/generated scenarios, but it is not MVP-critical. Initially allow manual minimization and retain generator seed plus full failing artifact. Later, a minimizer can reduce edit sequences, graph nodes or mutation parameters while re-running the relevant oracle.

Avoid corpus explosion by promoting **semantic equivalence classes**, not every duplicate failure. If 18 incidents reduce to the same stale-result invariant, keep representative regression instances plus randomized generation around that property.

### Benchmark-core verification

The benchmark framework itself needs release gates:

```text
manifest canonicalization tests
hash stability tests
cache-key mutation tests
cache-hit vs fresh-result tests
CAS corruption detection
worktree isolation tests
baseline contamination tests
mutation precondition tests
mutation verify-applied tests
mutation reproducibility-by-seed tests
fault-trigger verification
process-tree cleanup
network leakage tests
hidden-file visibility tests
evidence-reference integrity
replay equivalence
Windows path/case tests
Linux permission tests
```

A tiny internal `benchmark_selftest_project` is exactly appropriate for these tests. It should deliberately include:

```text
known passing tests
known failing overlay
known import graph
known mutation targets
known subprocess
known file writes
known crash point
```

But quality claims about Auto-Zoning or Auto-Refactoring should never be based mainly on that toy project.

### Implementation plan

I would split the MVP more narrowly than the proposed B1–B8 so that architectural invariants become testable before feature volume grows.

**B1 — experiment identities and immutable schemas**

```text
BenchmarkSpecVersion
ProjectSpec
TaskSpec
ScenarioSpec
ExperimentSpec
SuiteResult
canonical JSON
content digests
CLI skeleton
```

No real execution yet.

**B2 — repository materialization**

```text
Git repository cache
pinned SHA validation
source-tree digest
ephemeral worktree manager
cleanup/recovery
Windows + Linux tests
```

Git worktrees are a strong primitive here because Git directly supports multiple linked/throwaway worktrees sharing repository data. citeturn19view1

**B3 — environment and baseline health**

```text
EnvironmentFingerprint
uv/download cache integration
bootstrap command model
baseline runner
BaselineHealth
PASS / BASELINE_BROKEN / INFRA_FAILURE
```

**B4 — evidence and experiment DAG**

```text
BenchmarkRunBundle
CAS
StageResult
provenance
metrics
replay metadata
action keys
cache correctness tests
```

Content-addressed action/result separation follows well-established build-cache principles. citeturn19view0

**B5 — mutation and oracle primitives**

Start with very few:

```text
DUPLICATE_PROVIDER_DISPATCH
INTRODUCE_MUTABLE_GLOBAL
CREATE_CROSS_ZONE_DEPENDENCY

PROCESS_CRASH
TOOL_TIMEOUT
DUPLICATE_RESULT

FunctionalOracle
DifferentialOracle
OwnershipOracle
AuthorityOracle
```

Every mutation must have `verify_applied`.

**B6 — Auto-Refactoring first real suite**

Start with approximately:

```text
httpx
requests
pluggy or pytest
```

and small synthetic controls, including `KEEP_CURRENT` negative cases.

**B7 — Auto-Zoning over the same corpus/tasks**

Reuse exactly the same pinned projects and at least one shared TaskSpec, but give it independent ownership/responsibility fixtures.

This PR proves the central architecture rather than merely building another harness.

**B8 — firewall, private campaign support and CI selection**

```text
scenario projection
hidden overlay mounting
contamination ledger
changed-suite selector
PR/nightly/release campaign manifests
```

**B9 — broaden real corpus and add Architecture/Harness**

Only after the first two suites demonstrate useful reuse:

```text
AnyIO
Flask
Pydantic
SQLAlchemy

Architecture Assurance
Harness restart/fault subset
```

Then, later:

```text
graph generators
stateful property testing
coverage optimizer
historical mining pipeline
automatic minimization
distributed execution
```

Starting with Auto-Refactoring and Auto-Zoning is the right choice. They exercise the hardest conceptual boundary—**one repository and one workload, but radically different truth criteria**. If that separation is clean, Architecture Assurance, BADC, ECACC and Harness fit naturally. If those two suites become coupled through shared conclusions, adding more suites will only amplify the design error.

### What not to build in v1

Do not initially build:

```text
a general-purpose Scenario DSL language
a giant web dashboard SPA
a distributed benchmark scheduler
a Kubernetes benchmark control plane
a universal semantic graph service
a full Python source generator
automatic delta debugging
remote multi-node CAS
every possible fault injector
all twelve projects
all ten suites
four Python versions × every OS everywhere
one global scoring formula
automatic architecture "truth" generation from LLMs
benchmark-specific hooks in production
```

Also do not make `tox`, `nox`, `pytest`, Docker or `uv` the conceptual benchmark architecture. They are useful execution tools. The benchmark's durable abstractions are:

```text
Project
Task
Snapshot
EnvironmentFingerprint
Scenario
Mutation
Fault
Experiment
Stage
Observation
OracleResult
SuiteResult
Evidence
Provenance
```

Tools underneath can change.

### Economic model

Let:

```text
C = repository checkout/fetch cost
E = environment bootstrap/install cost
B = baseline-test cost
R_i = suite-specific cost for suite i
S = number of suites
```

Independent harnesses approximately pay:

```text
IndependentCost =
    S × (C + E + B)
    + Σ R_i
```

A correctly shared platform approaches:

```text
SharedCost =
    C per unique source snapshot
    + E per unique EnvironmentFingerprint
    + B per unique baseline action
    + cheap isolated worktree creation
    + Σ R_i
```

If ten suites really share one exact environment, the reusable checkout/install/baseline portion can **theoretically approach a tenfold reduction** relative to doing those phases independently. That is not a claim of tenfold total benchmark speedup: suite execution, LLM calls, mutations and capability-specific analysis remain. The largest real gain is likely to come from dependency installation, repository/test bootstrap and maintenance duplication, not from making the actual systems under test disappear.

There is also a maintenance multiplier:

```text
Independent:
    10 project bootstrappers
    10 result schemas
    10 environment-key implementations
    10 worktree implementations
    10 interpretations of INFRA_FAILURE

Shared:
    1 bootstrap model
    1 evidence envelope
    1 fingerprint contract
    1 worktree implementation
    1 infrastructure-failure taxonomy
```

That consistency is arguably more valuable than raw CPU savings because it makes cross-component regressions diagnostically comparable.

The major central-platform risks and controls are:

| Risk | Control |
|---|---|
| benchmark core bug damages every suite | small trusted core, self-tests, cache-vs-fresh sampling |
| shared corpus causes collective overfitting | private overlays, rotations, generated/metamorphic cases, contamination ledger |
| giant abstraction framework | manifests + narrow protocols; Python for complex behaviour |
| release coupling | suites independently versioned; affected-suite CI selection |
| slow CI | DAG caching, risk selection, covering arrays, rotating corpus |
| common oracle bug | suite-local oracle composition and independent mechanisms for critical properties |
| benchmark facade | one-way dependency + no benchmark mode + hidden projections |
| central cache poisoning | cryptographic digests + complete action keys + recomputation sampling |
| project-specific hacks | constrained ProjectAdapter contract |
| architecture benchmark encodes opinion | acceptable sets + forbidden invariants + mutation ground truth |

### Highest-ROI shared infrastructure

The pieces most likely to provide immediate multi-component leverage, in priority order, are:

| Priority | Shared piece | Why it pays off across the platform |
|---|---|---|
| **Highest** | **Immutable repository cache + ephemeral worktrees** | Every suite needs real repositories; eliminates repeated download/materialization while preserving isolation |
| **Highest** | **EnvironmentFingerprint + dependency/environment cache** | Installation is expensive and environment drift produces misleading failures |
| **Highest** | **BaselineHealth + reusable baseline evidence** | Separates target-repository breakage from SUT failures and avoids duplicate test runs |
| **Highest** | **BenchmarkEvidenceBundle + CAS + provenance** | Gives every component replayable, comparable and attributable evidence |
| **Very high** | **TaskCorpus + checkpoint/overlay model** | Allows one realistic task to exercise TaskOwner, Zoning, Architecture, Coder, Refactoring and Harness independently |
| **Very high** | **Shared MutationLibrary with suite-local expectations** | Reuses expensive defect construction without coupling capability judgement |
| **Very high** | **Fault injection + process/restart runtime** | Immediately benefits Harness, Zone Development, BADC, ECACC, Refactoring and integration |
| **Very high** | **Independent oracle primitives** | Prevents self-certification while avoiding duplicate differential/API/trace/test machinery |
| **High** | **Experiment DAG + correct content-addressed caching** | Reuses checkout/environment/baseline nodes while keeping suite executions isolated |
| **High** | **Benchmark firewall + contamination ledger** | Protects the validity of every LLM-assisted suite, not only one component |

The final architecture is therefore not:

```text
Shared Benchmark Platform
        =
everyone executes one giant workflow
        =
PASS / FAIL
```

It is:

```text
                    SHARED BENCHMARK PLATFORM

       ┌────────────────────────────────────────────┐
       │ Immutable Project Corpus                   │
       │ Immutable Task Corpus                      │
       │ Repository / Dependency Cache              │
       │ Environment Fingerprints                   │
       │ Worktree / Sandbox Runtime                 │
       │ Mutation & Fault Mechanics                 │
       │ Scenario / Checkpoint Composition          │
       │ Experiment DAG                             │
       │ Evidence / CAS / Provenance                │
       │ Metrics Infrastructure                     │
       │ Coverage / CI Planning                     │
       │ Replay / Reporting                         │
       └──────────────────────┬─────────────────────┘
                              │
              one workload may fan out
                              │
       ┌───────────────┬──────┴──────┬───────────────┐
       │               │             │               │
       ▼               ▼             ▼               ▼
 Auto-Zoning      Architecture   Refactoring       Harness
       │               │             │               │
 Ownership        Admissibility  Semantic/design   Recovery
 Oracle           Oracle         Oracle            Oracle
       │               │             │               │
       ▼               ▼             ▼               ▼
 Independent      Independent    Independent       Independent
 SuiteResult      SuiteResult    SuiteResult       SuiteResult
       │               │             │               │
       └───────────────┴──────┬──────┴───────────────┘
                              │
                              ▼
                    Evidence aggregation
                  WITHOUT verdict aggregation
                              │
                              ▼
              hard gates + capability vectors
                              │
                              ▼
                   release / regression view
```

The strongest architectural principle for the whole effort is therefore:

```text
MAXIMIZE REUSE OF:

    repositories
    immutable snapshots
    environments
    baseline computations
    workload definitions
    task overlays
    mutation machinery
    fault machinery
    execution infrastructure
    evidence storage
    provenance
    generic oracle mechanisms

MINIMIZE REUSE OF:

    conclusions
    labels
    authority judgements
    architecture preferences
    thresholds
    capability certificates
```

That design gives you the computational economy of one platform without turning autonomous-development verification into one opaque integration test. It also matches the central lesson emerging from modern repository-level benchmarking: realistic workloads and reproducible execution are necessary, but trustworthy evaluation increasingly requires **independent, compositional evidence rather than a single final outcome**. citeturn18view0turn7view0turn7view2