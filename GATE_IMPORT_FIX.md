# Runtime gate v4: separate pytest import domains

The supplied last-gate.log fails during collection of the real private harness
suite: tests.architecture_governance cannot be imported. No integration case ran.
Gate v3 passed a benchmark test path FIRST and all private paths to ONE pytest
invocation. Pytest still collects every path before executing any test, so this
was not the promised integration-first gate and allowed tests-package collisions.

Gate v4 runs two fresh Python interpreters through the existing ProcessRunner:
1. Both unchanged small/large real-runtime integration cases, with benchmark as
   test-package owner. Both exact parameter cases must pass.
2. All six unchanged private regression suite selections, with the staged ADCP
   as test-package owner. The real architecture_governance helper files are
   required, not synthesized. Each phase has its own explicit pytest rootdir,
   source paths, test namespace and module cache.

No production ADCP source, role adapter, PASS authority, size limit, payment
setting or user file is changed. Test namespaces bind to actual filesystem
package specs; no test implementations or fake PASS are injected. Workers reject
failures, collection errors and skips. A single existing 900-second outer
process deadline still applies; the inner phases share an 840-second budget.
The worker source participates in gate identity, so old receipts cannot qualify
this new gate. Original source hashes are rechecked before writing QUALIFIED.
Both phase XML/log files and an aggregate XML remain in .bench/runtime-validation.
The failed runtime is not activated and the existing installed runtime is kept.

Public regression fixtures deliberately model TWO synthetic test trees with
colliding tests namespaces, paths with spaces, relative fixture imports and a
cross-suite helper. They are process/import evidence only, not private runtime
or paid A/B evidence. Private source is not copied into the public repository.
Install the cumulative overlay into the existing START.cmd directory. Keep
.env, AB.toml, .bench, SOURCE.json and QUALIFIED.json intact. START.cmd handles the
retry automatically; no manual Python/package installation or reboot is needed.
