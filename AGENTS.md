# Run the existing automatic GitHub issue A/B; do not write another runner

Windows interactive: `START.cmd`.
Automation: set GITHUB_TOKEN and DEEPSEEK_API_KEY, then `START.cmd ab --allow-live-model`.
Linux: `python tools/prepare_ab.py ab --allow-live-model`.
No paid prompt: `START.cmd ab-preflight` (real issue qualification and real DSH boot).
No private ADCP required: `START.cmd qualify` (GitHub issue acquisition and qualification only).
Self-tests ONLY: `START.cmd test --offline`.

Read `.bench/latest.json`, then the named summary / RESULT.md. Open referenced logs only on failure.
Never dump .bench/, vendor/, source bundles, CAS, or benchmark-info.md into context.
Configure AB.toml: task count, repeats, resource caps, GitHub discovery and required project quotas.
The default project list is EMPTY: automatic public Python repository discovery.
There is NO synthetic or function-reconstruction fallback in the A/B path.

The launcher acquires the pinned private ADCP source with the user's read-only GitHub token.
The actual AA/ECACC/BADC runtime is PR28 b9c933bd7727b86149da891c323a27cde5afc956.
This is not the unpushed vNext CapabilityGateway build. Preserve this explicit identity.
Never publish .bench/adcp or private runtime artifacts to this public repository.

Stock DSH and all semantic roles use the genuine full SDK profile, not raw API prompts.
Same issue, base commit, image, test obligations and total per-arm budgets; separate workspaces.
All native workers see the full pre-fix repository. The legacy ADCP source view holds all editable
Python code (<=900,000 bytes); tests/config/assets stay protected in the full native workspace.
Unsupported projects/tasks are rejected before enrollment; failures afterward stay in the score.

Only original public tests feed repairs. PR tests/reference fix remain evaluator-only.
Missing/skipped/error required tests cannot become PASS. LLM messages never issue verification PASS.
Dollars remain null; request/output/time caps are NOT a hard dollar spending guarantee.
One task is a smoke comparison, not statistical proof of improvement.

Replay EXACT saved selection: `START.cmd ab --replay .bench/runs/<id>/selection.json --allow-live-model`.
Keep CAS objects and the exact project images. --seed alone is not replay of changing GitHub search.

Prerequisites: Python 3.12+, Git, running Docker with Linux containers, GitHub and DeepSeek access.
No paid model is invoked by infrastructure tests or qualification. User must authorize paid runs.
Small modules <=220 lines; reuse existing ProcessRunner, Git/worktree owners and CAS.
Map: corpus/discovery/automatic.py; corpus/qualification/; suites/coding/service.py,
issue_preparation.py, issue_campaign.py, native.py, cycle.py and provider/.
