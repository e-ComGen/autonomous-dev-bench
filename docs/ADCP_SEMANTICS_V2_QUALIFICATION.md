# ADCP Architecture Semantics v2 — benchmark compatibility qualification

This branch is a **post-preregistration compatibility path**, not a mutation of the
existing Phase 3D paid treatment.

Frozen paid experiment remains:

```text
ADCP treatment: e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13
pairs completed: 0/370
paid campaign started: NO
```

Semantics-v2 target is separately pinned in
`suites/coding/adcp_semantics_v2_contract.py`.

## Transport correction

The DeepSeek Harness adapter now distinguishes a provider turn that returned
`finish_reason=max-tokens` from an unknown external effect:

```text
max-tokens
  -> settled DeepSeekRoleResult
  -> partial final_response discarded
  -> RoleReply FAILED / MODEL_TURN_TRUNCATED
  -> ADCP Semantics-v2 bounded model-turn retry
```

Actual transport exceptions, invalid returned protocol data after dispatch, or
reply-persistence uncertainty remain `EFFECT_STATUS_UNKNOWN` and must be reconciled.

The old paid runner/lock is not silently switched to Semantics v2. A future full-system
experiment must be separately qualified/preregistered because Reviewer authority,
model-turn recovery, TaskOwner routing and Integration semantics are treatment changes.

## Validation status

The branch contains zero-paid unit coverage for the DeepSeek settled max-token
boundary. No paid call or campaign execution is authorized by this branch.
