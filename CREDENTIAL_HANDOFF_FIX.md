# Trusted host credential handoff

The new operator report loads ADCP 285702063815280398b95ba8696566259c8b5b34
with the 32 MiB snapshot ceiling, prepares the native SDK and then returns
GITHUB_TOKEN_MISSING with zero model calls. Its CAS diagnostics object is empty;
the other attached CAS object repeats that report. No expired credential,
HTTP rejection or new runtime-gate failure is evidenced.

The exact e7d64f4 entrypoint tools/bench.py scrubbed the host environment again,
retaining GitHub credentials only for discover. That removed BOTH GitHub and
DeepSeek keys already handed over by tools/launch.py, before GitHubReader
construction rather than during GitHub authentication.

The fix reuses tools.launch.host_environment and command_name in bench.py.
There is one existing command-scoped host policy, not another credential service
or permissive inheritance fallback. Help is classified as credential-free in
both callers. Diagnostic commands do not read .env.

Windows CI additionally caught the missing-key probe waiting for terminal input.
The existing spend admission now refuses missing keys immediately when explicit
paid automation is selected, regardless of the stdin isatty result. Interactive
manual admission without that selection is unchanged. No new prompts or budgets.

The runtime pin, gate identity inputs, verification authorities and worker
environment builders are unchanged. GitHub is available to acquisition commands;
DeepSeek only to ab's trusted host. Bootstrap/native/build/test children retain
their existing explicit scrubbed environments. Native is still NOT an OS sandbox.
No config rewrite or budget change is introduced.

Tests execute actual bench.py in subprocesses for file/env/alias credentials,
nonpaid commands, malformed .env diagnostics, missing keys and repeated handoff.
They construct the real GitHubReader and call the real spend admission using
non-secret test values but perform no HTTP/model calls. Real child processes
verify that bootstrap and native environment builders do not inherit these values.
The noninteractive missing-key tests cover both possible stdin isatty results.

The exact-old/new experiment runs identical tests against the previous and new
entrypoint bytes, with the same noninteractive spend admission in both runs.
The packaged experiment additionally traverses actual START.cmd -> start_ready.py
-> launch.py -> bench.py, including genuine launcher venv provisioning from bundled
verified wheels. Only private acquisition and terminal CLI dispatch are explicit
test probes in temporary copies. Neither experiment constitutes paid A/B or
private-runtime qualification; production paths have no new test doubles.

Install the coherent overlay contents beside START.cmd with replacement. Preserve
.env, AB.toml and .bench. Existing valid runtime qualification is reusable through
normal identity checks; never edit SOURCE.json or QUALIFIED.json manually.
