# Coherent host overlay and gate finalization

The operator's gate-v4 log shows BOTH private phases passing: two actual
small/large repair integrations, and 495 regression tests plus 109 passing
subtests. It then fails during host cleanup because the loaded ProcessRunner
has no cancel_running method. This is not an ECACC/AA/BADC test failure and
not a paid coding-quality result. The exact origin/hash of that loaded host
module is not in the supplied log; no particular installation mistake is inferred.

The published benchmark core already implements cancel_running. Previous
small overlays included only the diff against the source-fast base, not
unchanged core dependencies. The new overlay refreshes every tracked public
host source/test/resource under the application directories and the batch
entrypoints. It does not include .env, AB.toml, BENCHMARK.toml, benchmark.lock,
vendor, or .bench. OVERLAY_SOURCE.json records the exact payload hashes.

Before private execution, the gate now requires the real local process owner
and both required methods. A shadowed/stale host is rejected BEFORE expensive
tests, with its module path. Host core bytes are also included in gate identity.
No getattr/no-op cleanup fallback, fabricated qualification marker, skipped
private test or change to model verification authority is used.

Packaging validation applies the actual overlay to an older complete release
with a deliberately incompatible process API and preserved operator-state
sentinels. It checks repaired source hashes and executes that updated checkout.
Public process/layout tests also exercise gate main through combined JUnit and
QUALIFIED.json creation, not just its two pytest children. Synthetic layout
checks are explicitly not private runtime or paid model evidence.

Install: stop the old process, extract overlay CONTENTS next to START.cmd with
replacement, then run START.cmd normally. No manual file edits, new switches,
Docker, reboot or payment prompts. Do not modify SOURCE.json or QUALIFIED.json.
The gate requalifies the new exact host/runtime binding; old XML alone is not
used to manufacture an activation receipt. Private source pin is unchanged.
