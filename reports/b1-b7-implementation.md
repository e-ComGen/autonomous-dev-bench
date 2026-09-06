# B1–B7 implementation report

## Delivered

- Immutable, canonical and content-addressed project/task/scenario/experiment models with explicit audience projections.
- Pinned Git acquisition, canonical Git-tree SHA-256, disposable worktrees, copy fallback, pristine verification and recovery.
- Exact virtual-environment bootstrap, complete environment/baseline action identities, CAS-backed baseline execution evidence, status separation and fail-closed baseline admission.
- Dependency-keyed DAG, filesystem CAS with read verification, SQLite action cache, mandatory evidence bundle envelope, stage integrity, provenance, replay and coverage selection.
- Deterministic mutation recipes with independent application verification and rollback; process/tool/protocol fault injectors.
- Independent functional, differential, public-API, trace, ownership, authority and recovery oracle primitives.
- Auto-Refactoring v4 and Auto-Zoning v3 suites with different checkpoint projections, labels, metrics, oracle compositions and hard-gate behavior.
- Benchmark-owned adapters matching the current Auto-Refactoring v0.10 Design-Form and Auto-Zoning v0.6 semantic APIs. In-process adapters are deliberately rejected for authoritative runs.
- Pinned HTTPX, Requests and Pluggy corpus manifests; a shared HTTPX task/scenario; a standalone synthetic self-test project.

## Verification performed

- Platform unit/integration suite: 116 passing tests plus two opt-in local-production tests.
- Standalone self-test project: 2 passing tests.
- Coverage gate: 80% required; final measured branch coverage 80.08%.
- Clean sdist and wheel build; clean-venv wheel import, installed corpus assets, and CLI `list-suites` and `zoning-preview --help` smoke tests.
- Realized HTTPX virtual environment and deterministic baseline policy: PASS with CAS evidence.
- Opt-in baseline-gated diagnostic HTTPX run through `ExperimentRunner`, the real Auto-Refactoring v0.10 CLI, executable HTTPX lifecycle/API oracles, and the real Auto-Zoning v0.6 subprocess worker: 1 passed. Authoritative admission requires a pinned sandbox attestation; the core ships a digest-pinned, network-denied Docker provider, while the local production integration remains deliberately diagnostic.
- Dependency firewall passed against the current Auto-Refactoring, Auto-Zoning and DeepSeek Harness trees.

## Campaign boundary

The repository ships deterministic public development bindings for the HTTPX task/fixture and pinned mutation parameters. A sealed campaign replaces the development oracle context with private evaluator-side labels and independently executes feature/differential/public-API probes through `RefactoringOracleExecutor`; private labels are never committed or mounted into the SUT.

B8+ private campaign management, contamination ledgers, distributed workers and additional capability suites remain outside this milestone.
