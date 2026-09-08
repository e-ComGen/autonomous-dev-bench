# Native qualification completion

Keep using START.cmd and the same .env. No payment/local confirmation is reintroduced.
The private ADCP pin is upgraded transactionally: download, verify, run actual runtime
regressions plus the benchmark role-port integration, then activate. The previous
.bench/adcp is retained as a backup. Failed checks prevent activation and paid calls.
Logs: .bench/runtime-validation/last-gate.log and its JUnit files. A ten-second heartbeat
shows that the one-time gate is active. This gate is NOT a coding-quality score.

Code admission now defaults to 16 MiB; the explicit ADCP snapshot allocation is
32 MiB including public task helpers. An unchanged repository asset can be up to
16 MiB within the existing aggregate repository cap. Files are not silently dropped.
Existing stricter values explicitly set in your AB.toml continue to apply.

Native builds prefer wheels, but can build source distributions at their requested
versions. atomicwrites==1.4.1 is not downgraded. Dependency wheels are frozen and
hashed once; both arms install those exact assets into fresh environments.
An actual pre-fix import of curses/_curses on Windows adds windows-curses==2.4.2
to the declared build recipe. Other platforms and comments do not add this package.
Project build scripts still run under the operator's local trust; no OS sandbox is claimed.
CUDA, external services, unsupported Git modes and genuinely incompatible projects
can still be rejected. No disabling pytest, skipping failed imports or fake PASS.

Repeated expensive preparation is bounded separately per project per campaign.
The effective quota is max(github.preparation_attempts_per_project, github.tasks_per_project),
with the new attempts field defaulting to 2. Deferred candidates are reported as
PROJECT_PREPARATION_QUOTA at stage sampling, not as invalid source or failed tests.
No permanent blacklist, negative-result cache or prediction across different commits is added.
The actual count of preparations is recorded separately from metadata candidate count.

Validation distinguishes public host tests, actual dependency-wheel experiments,
private runtime qualification and paid A/B. None can substitute for another.
