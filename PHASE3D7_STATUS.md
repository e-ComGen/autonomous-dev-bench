# Phase 3D7 status

`PHASE3D_EXPERIMENT_PLAN.json` is now outcome-blind **LOCKED** from the machine-generated Phase 3D6 candidate.

Selected design:

- sensitivity scenario: `mde-15pp-conservative-discordance`;
- target power: 0.80;
- achieved exact power: `0.8073632070304838`;
- 37 repeats per task;
- 370 required completed pairs;
- 740 total arm runs;
- per-arm total model-token cap: 262,144;
- per-arm input component cap: 262,144;
- per-arm output component cap: 65,536;
- per-arm request cap: 16;
- per-arm wall-time cap: 600 seconds;
- per-arm patch cap: 262,144 bytes.

Immutable identities:

- pre-lock plan digest: `sha256:710abee3b025bab46358400c0d5a702e1c3fceb5037c3df861a061053977786e`;
- locked plan digest: `sha256:725944356ef66c8bd0e473bfe19016b06b7883b9c0ef72cf8135850b01864d97`;
- selected assumptions digest: `sha256:01f35c00573f90942b0c292d119fd36b9826bfab3bd947fd2e9c07a95120a9ce`;
- pair schedule identity: `sha256:50a62fab288731caca4e1667155600f0de19dadcf5123d106d2ade7c53d23e54`.

The accepted candidate was generated and verified without outcome data or model calls by workflow run `34377005625` at head `f4ccb8a8b91b84da102a53e450a2130f8fe993c1`; artifact `10114288168` has digest `sha256:8ffd64384c86fcd4671f11b3956f6885a52d9305a6f8d35c5fe3e3ffc2fad693`.

`design_paid_ready=true` means the **scientific design fields are complete**. It does not bypass external paid-admission gates. DeepSeek live prompt-token parity and the exact pinned private ADCP runtime qualification remain independently required.

No paid paired experiment has run. `PAID_PAIRED_AB` remains `NOT_RUN` and `winner` remains `UNKNOWN`.
