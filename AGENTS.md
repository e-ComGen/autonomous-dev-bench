# Run first, do not implement a replacement benchmark

Default user action is **random coding A/B**, not infrastructure self-test.

Windows: `START.cmd` (interactive confirmation and hidden key entry).
Automation with DEEPSEEK_API_KEY already in the environment:
`START.cmd ab --allow-live-model`
Linux: `python tools/launch.py ab --allow-live-model`
Replay selection: append `--seed <recorded integer>`; keep AB.toml and release unchanged.
No paid calls: `START.cmd ab-preflight` (Docker build, task qualification, actual SDK boot).
Infrastructure only: `START.cmd test --offline`.

Read `.bench/latest.json`, then the referenced summary. Open only referenced diagnostics on failure.
Never dump .bench/, vendor/, all source bundles, full traces, or benchmark-info.md into context.
Settings: AB.toml for coding A/B; BENCHMARK.toml for corpus foundation commands.
Prerequisites: Python 3.12+, Git, Docker with Linux containers. Initial image build needs internet.

Do not replace DSH with raw API prompting or emulate ADCP roles in a new loop.
The private release includes the actual pinned PR28 ADCP runtime in `.bench/adcp`.
It is not the unpushed vNext archive; report its exact runtime identity, not a vNext gateway claim.
The stock arm and all semantic cycle roles share the full native DSH SDK profile.
AA/ECACC/BADC run in the existing ADCP package; no model can vote verification PASS.

Default tasks are real-source FUNCTION RECONSTRUCTION smoke tasks over three pinned packages.
They are not mined issues, full-repository SWE scores or representative large-project tasks.
Do not silently replace a failed enrolled task with a different one.
Hidden cases and reference implementations stay evaluator-only.
An empty patch or a model message saying PASS must not pass acceptance.
Request/time caps are enforced; dollars remain null, not zero or an enforced dollar budget.
Keep source modules <=220 lines. Existing process/Git/worktree/CAS owners must be reused.

Implementation map: suites/coding/service.py (composition), selection.py, evaluation.py,
native.py, cycle.py/cycle_roles.py, docker_runtime.py, provider/ (credential relay/accounting).
Do not publish the private ADCP distribution to the public benchmark repository.
