# autonomous-dev-bench

Reusable benchmark/evaluation infrastructure for the e-ComGen autonomous software-development ecosystem.

The platform shares immutable repositories, environments, baseline evidence, tasks, mutation/fault mechanics, runtime and evidence storage while preserving **independent capability oracles, labels, hard gates and results**. It intentionally exposes no universal autonomous-development score.

## Milestone

The initial implementation covers:

- **B1** immutable schemas and experiment identity;
- **B2** Git materialization and disposable worktrees;
- **B3** environment fingerprints and baseline health;
- **B4** CAS, action cache, evidence bundles and experiment DAG;
- **B5** mutation, fault and independent oracle primitives;
- **B6** Auto-Refactoring suite and production adapter;
- **B7** Auto-Zoning suite and production adapter.

See [`docs/architecture.md`](docs/architecture.md) for boundaries and security invariants and [`reports/b1-b7-implementation.md`](reports/b1-b7-implementation.md) for verification evidence.

## Dependency rule

```text
autonomous-dev-bench  --->  normal production APIs
production packages   -X->  autonomous-dev-bench
```

Do not add this package to a production dependency graph. Do not add benchmark-specific code paths to a production package.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
```

Authoritative execution is fail-closed: it requires a typed `ExperimentSpec` binding project/task/scenario/system/suite/attempt/seed and content-digested private labels/oracle code, typed materialization identities, a content- and executable-pinned SUT, an attested sandbox provider resolved from an operator-owned `SandboxTrustStore`, a realized environment with CAS-backed green baseline evidence bound to that attestation, exact planned metrics/gates, and a finalized evidence bundle with an external root receipt. Plain host subprocesses and in-process adapters remain diagnostic only. `benchmark_core.DockerSandboxProvider` provides a digest-pinned, read-only, network-denied container backend; it deliberately does not claim package-index allowlisting.

The CLI exposes validation, digest, evidence verification and suite-manifest inspection:

```bash
autonomous-dev-bench --help
```

## Hard gates

A run is unsuccessful if any critical counter is nonzero, regardless of all other metrics: false-safe certification, unauthorized cross-zone write, half-applied transaction, accepted stale candidate, lost required verification, or evidence-integrity failure.

## Corpus policy

Public corpus manifests pin full commits and canonical source digests. Public development scenarios may ship deterministic fixture/mutation bindings for reproducibility. Sealed campaign labels, private mutations and oracle material live in a separate store and are never mounted into the system-under-test workspace; task projections expose only stage-appropriate public inputs.
