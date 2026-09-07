# Automatic real-issue A/B: native Windows or Docker

Extract the whole archive. On Windows double-click START.cmd: native execution is now
selected automatically. Docker, WSL, Hyper-V, administrator installation and reboot are
NOT required by this backend. Python 3.12+ and Git are prerequisites. The launcher installs
SDK/runtime and project Python dependencies in local venvs without changing global packages.
See NATIVE_WINDOWS.md for the Russian operator guide.

The launcher obtains a GitHub read token for discovery and the existing private ADCP runtime,
then requests explicit LOCAL consent before executing downloaded code on the host. It searches
real public Python repositories/issues, captures before/after commits, prepares an environment,
checks bug reproduction and regressions, freezes one task and executes both systems after
separate paid-model authorization. Unsupported projects are rejected before enrollment.
There is no replacement with reconstruction tasks or infrastructure self-tests.

## Important native-mode boundary

A native venv isolates Python dependencies, NOT your files, network or credentials on disk.
Downloaded builds, tests and agent commands run as your user account. Their environment is
filtered and they do not receive API keys, but same-user processes are not OS-isolated.
Hidden tests are not supplied as agent input, yet native mode cannot prevent a process reading
host files. Treat this as explicitly trusted local execution, not a hostile-code sandbox.
CPU/RAM caps are Docker-only; reports mark them unenforced natively. Time/request/output
limits remain active. Dollars are unpriced/null, not zero or a guaranteed spending cap.

## Commands

START.cmd: interactive native A/B on Windows; auto selects Docker on Linux.
START.cmd ab --backend native --allow-local-execution --allow-live-model: authorized automation.
START.cmd ab-preflight --backend native --allow-local-execution: preparation and SDK/ADCP checks, no paid prompt.
START.cmd qualify --backend native --allow-local-execution: real issue preparation only; no private ADCP/model needed.
START.cmd test --offline: infrastructure self-tests only.
START.cmd ab --backend docker: explicitly retain the container execution backend.
Use python tools/prepare_ab.py with the same arguments outside Windows.

AB.toml sets execution_backend=auto|native|docker, tasks/repeats, budgets and [github] selection
policy. No explicit repository list is required. Required size quotas count distinct qualified
projects; unsupported native packages are reported rather than replaced by small fixtures.

## Results and replay

.bench/latest.json -> summary.json and RESULT.md. Source, environment, task/issue, seed,
execution backend and limits, both outcomes, token counts, patches and evidence are recorded.
Large logs are referenced through the existing CAS or retained native provisioning logs.
Do not dump .bench/native, wheelhouses, source bundles or full traces into model context.

Replay uses --replay <selection.json>, the same settings/implementation and retained .bench.
Native wheel manifests and interpreter bindings are checked before reuse. Each project actor
and evaluation invocation receives a fresh venv installed without network from those wheels.
A Docker image ID is not silently replaced with a native environment or vice versa.

## Existing scope

Python/pytest issues that change existing source files and have separable historical regression
tests are supported. The public regression sample may not be the whole upstream test suite.
Historical tasks may have been in model training. No contamination-free/general coding gain claim.
B remains the real pinned PR28 AA/ECACC/BADC runtime, NOT a new emulated loop and NOT the earlier
unpublished vNext archive. Private source is acquired on the authorized machine, not published.

CI evidence explicitly separates host tests, native SDK transport fixtures, actual upstream
issue qualification and paid A/B. A fixture response or green self-test never proves model quality.
