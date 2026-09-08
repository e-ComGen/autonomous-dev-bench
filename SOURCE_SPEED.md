# Exact source acquisition update

Stop a running benchmark before applying the small source overlay. Extract its CONTENTS
beside the existing START.cmd and replace files. Keep .env, AB.toml and .bench.
Then launch START.cmd normally. Paid-default/no-prompt behavior is unchanged.
The complete archive is an alternative for a NEW directory, not another required layer.

Changes:
- Existing SharedGitCache now obtains only requested full-SHA commits with a shallow
  no-tags fetch. Existing mirror caches remain usable. A warm exact pin needs no fetch.
- Tree hashing and canonical worktree materialization use one batched Git blob reader
  per operation, including verification of each Git object ID and byte count.
- Exact tree size/mode/path checks precede blob hashing and worktree creation. This
  happens AFTER pinned fetch, not a promise that network bytes were prefiltered.
- Acquisition prints a stage and elapsed time every five seconds. progress.json records
  stage timings; timeout errors retain the last known stage rather than just TIMEOUT.
- The paired run freezes source/objective/environment/settings bindings. Every role in
  the cycle shares the same arm token and request budget. Native materialization cannot
  renew the arm's deadline. Pair/result mismatches fail closed.

Existing hashes, negative/positive task controls, hidden acceptance, stock DSH profile,
ADCP/ECACC/BADC owners, credential isolation rules and no-resampling policy remain.
There is no new cache service, scheduler, verification authority or replacement loop.

Validation artifacts distinguish local Git performance, host tests and actual issue
qualification. None is a claim of paid A/B completion or improved model coding quality.
The local 512-file microbenchmark compares the exact previous implementation and same
byte-identical pin, counting actual Git processes and measuring cold and warm operations.
Real-network qualification is separate and uses the explicitly declared CI repository pool.

Not completed by this release:
- The current private ADCP pin still has a 1,000,000-byte session ceiling; the benchmark's
  editable code view remains capped at 900,000 bytes. A proposed batched/private large-source
  extension is on fix/bounded-large-source-snapshots but its private CI did not execute.
  It is NOT silently patched into operator runtimes and is NOT activated here.
- No paid full-cycle canary was executed in this build environment.
- Request and requested-output caps do not provide an exact input-token or dollar cap.
- Native mode is not a filesystem/network sandbox; it runs with the operator's permissions.

For current validation, read SOURCE_VALIDATION.json and validation-source/.
For an actual run, read .bench/latest.json and its summary, then only referenced diagnostics.
