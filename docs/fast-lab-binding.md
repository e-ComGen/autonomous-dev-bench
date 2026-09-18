# Explicit LAB backend for FAST

The existing campaign plan/execute/summarize commands accept `LAB_HOST_ONLY` in
the task's single shared execution configuration. The legacy `CLI_JSON` route
is unchanged. Planning, validation and dry-run never import or invoke LAB.

LAB execution fields are exact: `route: LAB_HOST_ONLY`, `provider: deepseek`,
`model: deepseek-v4-flash`, `thinking: EXISTING_PROVIDER_DEFAULT`,
`native_tools: []`, `lab_root`, `python_executable`, `dependency_manifest` and
`config` (each `{path, sha256}`), and `dsn_env_keys: {A: ENV_KEY_A, B: ENV_KEY_B}`.
DSN keys must differ; secrets are provisioned outside the manifest. The hashed
configuration carries the existing bounded LAB budgets; this interface adds no
attempts, repetitions, budget overrides or retries.

Each context packet must be exactly a JSON object with `context_policy`:
`ordinary` for A, `zone_preferred` for B. Task text remains the frozen manifest
task. Source packets and native scaffold are not injected. A native
`packet_quality_gate` cannot qualify these new packets and is rejected. Existing
hash-bound functional evaluator manifests remain required and unchanged: the
first supported source is the existing six expansion FAST manifests. A task
without a compatible manifest is BLOCKED; this binding creates no oracle,
acceptance category or alternative task framework.

The Python callback contract is:

```python
execute_pair(pair_dir, authorized=True, lab_backend=callback)
callback(*, manifest: dict, plan: dict, arm: str, arm_dir: Path) -> dict
```

The production default lazily imports `adcp_lab.runtime.fast_ab.execute_arm`
only on LAB execution. Launch the CLI using the bound interpreter with that
module installed from `lab_root`. A missing hook or mismatched module/interpreter
fails the arm closed. The legacy `executor` hook is prohibited for LAB.

The callback owns a fresh LAB workspace and session for each arm. FAST's
`plan.arms[arm].workspace` is only a frozen source identity snapshot and must not
be mutated. FAST does not copy a LAB candidate, replay a patch, run a native
agent, or fabricate `agent_end` events. The callback validates LAB evidence and
returns these required fields:

- `metrics`: explicit boolean `execution_success`, `model_executed` (null only on incomplete failure), and
  `model_turns`, `tool_calls`, `read_calls` (nonnegative integers or null when
  unobserved). Other observed resource metrics are optional.
  Actual model payload `packet_bytes`, `source_bytes`, `source_item_count`, and
  `total_wall_time` are preserved; absent measurements remain null. The JSON
  policy file size is recorded separately as `policy_packet_bytes`.
- `evaluation`: the exact frozen `evaluation_plan_digest` and `results` keyed
  by every frozen evaluator ID, with existing evaluator statuses.
- `patch_valid`: an explicit boolean derived from LAB patch evidence; null on incomplete failure.
- `lab_evidence`: `projection_validated: true` plus the actual validated LAB
  evidence. Functional evaluator results remain separate from integrity/ECACC.
- `treatment`: a nonempty canonical JSON object describing actual treatment,
  excluding arm labels, plus `treatment_digest = plan_digest(treatment)`.

Subprocess exit zero alone is insufficient. Each arm is claimed once, in the
existing seeded order; a callback exception or malformed result fails that arm
while the other still runs. No treatment difference excludes the pair from
comparative conclusions and campaign denominators, retaining raw evidence.

Incomplete failures retain `projection_validated: false` with an explicit projection error, known usage and separate unknown integrity/evaluator dimensions. They cannot qualify as successful execution. Interrupted pairs are never resumed or used as readiness evidence.
