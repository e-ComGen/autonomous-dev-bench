# Run first. Do not invent another loop or replace real issue tasks.

Windows default: `START.cmd` selects NATIVE execution. No Docker, WSL, admin install or reboot.
Python 3.12+ and Git are needed. All SDK/project Python dependencies are provisioned locally.
Native execution needs explicit user consent: downloaded code runs with user-account permissions.
It is NOT an OS sandbox; no enforced filesystem/network isolation or CPU/RAM ceiling.
Do not silently grant consent or switch execution backend after a failure.

Automation after local-code and model-spend authorization, with keys already in environment:
`START.cmd ab --backend native --allow-local-execution --allow-live-model`
No paid prompts: `START.cmd ab-preflight --backend native --allow-local-execution`
Real issue preparation only: `START.cmd qualify --backend native --allow-local-execution`
Infrastructure tests: `START.cmd test --offline`
Linux equivalent: `python tools/prepare_ab.py ...`
Docker remains explicit: `--backend docker`; auto on Linux selects Docker.

Read `.bench/latest.json`, then its summary/RESULT.md. Open referenced logs only on failure.
Never dump .bench/, vendor/, whole issues, bundles or benchmark-info.md into agent context.
Settings: AB.toml. Defaults select ONE real GitHub issue and BOTH existing execution paths.
Do not replace DSH with raw model API or the actual ADCP runtime with an emulated role loop.
B is the exact PR28 runtime, NOT the separate unpushed vNext adapter; report its identity.
AA/ECACC/BADC remain original. Hidden evaluator feedback never enters model repair.

Native execution reuses project wheel assets but makes a fresh project venv per invocation.
Private source acquisition requires a GitHub read token unless ADCP was already provisioned.
The production relay is localhost-only in native mode; real credentials are not put in child env.
Native mode cannot prevent other same-user processes reading host files, including test assets.
No claim of strict secret/test isolation or hostile-code benchmark authority in native mode.
Request/output/time budgets remain active; cost is unpriced/null, never an invented zero.

Source: suites/coding/backend.py selects a mechanism; backends/ contains only native execution.
Existing service.py/issue_campaign.py own A/B; existing corpus/qualification owns task validity.
Existing ProcessRunner/Git/worktree/CAS owners must be reused. Keep new modules <=220 lines.
Do not publish private ADCP code to this public repository or CI logs/artifacts.
