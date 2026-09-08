# A/B backend compatibility and early configuration validation

The latest operator upload has a combined zero-failure runtime JUnit with both
actual small/large repair integrations and the original regression selection.
The subsequent ab report stops on `Unknown A/B settings: ['backend']` before any
model call. The operator's AB.toml itself was not supplied, so no other local
values or origin of the legacy spelling are inferred from this error.

The existing Settings loader now accepts the root-level TOML spelling `backend`
as an input alias for `execution_backend`. The canonical dataclass, reports,
selection locks and backend selection retain execution_backend. Both equal
spellings are accepted; conflicting values, invalid types/values, unknown
settings, invalid budgets and project quota errors remain failures. The file
is never rewritten and no configured budget is defaulted away.

START.cmd validates this same configuration before private runtime acquisition.
--ab-config (including custom paths) and --backend overrides use the shared
loader; CLI precedence does not hide a conflicting or invalid TOML file.
The direct prepare_ab entrypoint also uses the same early reader. Help and
non-A/B diagnostics remain independent of A/B configuration and paid calls.

The fix does not change the private source pin, core process implementation,
verification adapters, gate workers or named runtime tests. A valid existing
QUALIFIED receipt for unchanged gate inputs can therefore be reused normally;
no receipt is synthesized or bypassed. The combined XML alone does not prove
that the operator has an installed receipt, so successful reuse is conditional
on that existing marker and the normal source/identity checks.

Validation includes strict parser tests, real START.cmd subprocesses on Windows
with a legacy config and test-only acquisition/dispatch boundaries, and real
service admission stopped before runtime creation. The exact old/new reader
comparison must reproduce the operator error before and pass after, preserving
all configured settings and bytes. These are not live model results.

Install the coherent overlay CONTENTS beside the existing START.cmd with file
replacement, then run START.cmd normally. Do not edit AB.toml or .env, delete
.bench, or modify SOURCE.json/QUALIFIED.json. New early output: Config: settings-v2.
