# Architecture

## Decision

This repository is a shared experimental substrate, not a universal scorer.

```text
SHARED INPUTS + SHARED INFRASTRUCTURE + SHARED MECHANICS
                              |
              independent suite projections
                              v
INDEPENDENT ORACLES + LABELS + HARD GATES + SUITE RESULTS
```

The benchmark may invoke normal production APIs or subprocess entry points. Production packages must never import this repository, emit benchmark-specific types, or contain a `benchmark_mode` branch. Production certificates are observations, never benchmark truth.

## Trusted boundaries

`benchmark_core` owns immutable identities, checkout/worktree materialization, environment fingerprints, execution, action keys, CAS, evidence, replay and generic mechanics. `mutations` describe and verify the world they create. `faults` operate at real process/tool/protocol boundaries. `oracles` provide independent measurement primitives. Each package under `suites` owns its own labels, oracle composition, policy, thresholds and `SuiteResult`.

Suites cannot override checkout, isolation, CAS or evidence behavior. Project adapters may customize bootstrap commands only; they cannot contain expected architecture or hidden labels.

## Checkpoint model

A scenario is declarative and answer-free. Its checkpoint DAG composes a pinned source with task/fixture/mutation overlays. Auto-Zoning consumes the task-ready checkpoint. Auto-Refactoring consumes a candidate checkpoint. Expected answers are supplied only through suite-local oracle contexts, which are never mounted into the system-under-test workspace.

## Advisory real-project zoning previews

The preview lane is intentionally separate from suite evaluation. It materializes a pristine pinned project and asks Auto-Zoning for either true `FULL` analysis (`seeds=None`) or explicit repository-relative `PATHS`. No private labels or task oracle are loaded, and every output is marked `advisory: true` and `authority: NONE`.

Independent uncached repetitions verify the source tree before and after execution. Stability uses the production `analysis_digest` and a canonical normalized proposal, not volatile timestamps or telemetry. Deterministic summary JSON and Markdown are separated from raw per-run production payloads. `PARTIAL` analysis remains visible rather than being promoted into a correctness verdict; source races, process failures, malformed output and version mismatches fail the preview.

## Content identity and caching

Friendly IDs are labels, not cache keys. Canonical JSON and SHA-256 identify specifications and artifacts. Environment keys include every behavior-relevant platform, interpreter, dependency, adapter, policy and environment-variable field. Baseline keys additionally include command, executor and test-policy versions. Observation and oracle action keys include their complete dependencies and remain suite-local where semantics are involved.

`ProjectEnvironmentBuilder` realizes the exact bootstrap declaration in a dedicated virtual environment, fingerprints the interpreter and resolved dependencies, and runs every declared deterministic baseline command. Authoritative admission requires a complete ordered receipt for every declared baseline command; command/action/cwd, executor/policy revisions, environment, sandbox attestation, PASS status, and CAS execution bytes are recomputed before use.

The filesystem CAS verifies bytes on every read. SQLite stores action-key to CAS-reference metadata; it does not replace content verification. Evidence envelopes require exact pinned experiment/environment/SUT/suite/oracle/policy fields, CAS-backed stored artifacts, and verification against an externally retained root receipt rather than trusting the mutable bundle's embedded root.

## Failure semantics

Infrastructure, target baseline and capability failures are distinct. A mutation that cannot prove it was applied is `INVALID_EXPERIMENT`. Unknown authority blocks mutation. No metric can compensate for any nonzero critical counter:

- `false_safe_certificate`
- `unauthorized_cross_zone_write`
- `half_applied_transaction`
- `accepted_stale_candidate`
- `lost_required_verification`
- `evidence_integrity_failure`

There is deliberately no `AUTONOMOUS_DEV_SCORE`.

## Production adapters

Adapters are benchmark-owned anti-corruption layers. The Auto-Refactoring adapter invokes the pinned production CLI in an isolated environment and preserves raw status, stdout, stderr, changed paths and claimed certification; suite oracles independently validate semantics and false-safe behavior. The Auto-Zoning adapter consumes the read-only semantic frontend/projection and retains `PARTIAL`, unknown mass and `authority=NONE`; it never upgrades a proposal to an accepted ownership manifest. Direct in-process production adapters are non-authoritative diagnostics only. Authoritative execution accepts only a benchmark-owned command-adapter contract: the runner itself executes the `CommandSpec`, sanitizes the environment, enforces the scenario timeout/network/mode, captures CAS evidence, and parses the neutral observation. An adapter-owned marker cannot opt into authority.

## Security and firewall

Authoritative execution requires an operator-trusted sandbox provider whose ID and implementation digest match the policy trust root; caller-supplied capability booleans are not accepted as authority. The shipped `DockerSandboxProvider` accepts only digest-pinned images and advertises only network-denied, read-only-root execution. It also requires a fresh writable worktree and temporary directory, command cwd confinement, forced TMP/TEMP/TMPDIR, no execution network, sanitized environment, resource/time limits and process-tree cleanup. Diagnostic runs without a finalized bundle explicitly fail the `evidence_integrity_failure` global gate. Hidden manifests stay outside this checkout and are not mounted into the SUT. Only task projections cross the boundary. Benchmark IDs, mutation parameters, seeds and oracle labels remain in evidence-side storage. Public repositories are untrusted code.

The full private-campaign/contamination system is B8, but these fail-closed boundaries are required in B1-B7.
