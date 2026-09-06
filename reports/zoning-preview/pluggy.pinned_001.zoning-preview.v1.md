# Auto-Zoning preview: pluggy.pinned_001

> **Advisory only. Authority: NONE. This is not an architectural certification.**

- Commit: `fd08ab5f811a9b2fa9124ae8cbbd393221151e2c`
- Source tree: `sha256:82bdbb16b3d3468bd5355b3fc0c10993537a144d514e999d4dc03a04e47eede9`
- Scope: `FULL`
- Stability: **STABLE**
- Analysis digests: 1
- Proposal digests: 1
- Exact assignment retention: 1.000000
- Co-zoning pair Jaccard: 1.000000
- Semantic boundary Jaccard: 1.000000

## Coverage and uncertainty

| Metric | Value |
|---|---:|
| Proposal mass | 0.182927 |
| Partial mass | 0.817073 |
| Unknown mass | 0.000000 |
| Budget exhaustion reasons | 0 |
| Missing obligations | 0 |
| Parse errors | 0 |

## Proposed zones

| Zone | Display name | Responsibilities | Artifacts |
|---|---|---:|---|
| `zone-proposal_40810f0a418586590a13cc2e` | <file:scripts/release.py> · changelog / create_branch / pre_release behavior | 1 | `scripts/release.py` |
| `zone-proposal_45a509d66fbfabba560ed746` | eggsample.host · condiments_tray / ingredients state | 4 | `docs/examples/eggsample/eggsample/host.py` |
| `zone-proposal_53e6797b43aa6423956ae6a4` | pluggy._result · _exception / _result / _traceback state | 1 | `src/pluggy/_result.py` |
| `zone-proposal_7bcfcb07cc1f9e393bdf783f` | cross-module · _inner_hookexec / _name2plugin / _plugin_distinfo state | 7 | `docs/examples/toy-example.py`, `src/pluggy/_manager.py`, `testing/benchmark.py`, `testing/test_details.py` |
| `zone-proposal_ba568823a83486bb12bac355` | pluggy._tracing · _tags2proc / _writer state | 2 | `src/pluggy/_tracing.py` |
| `zone-proposal_c9f9e8f5d80d7d34d17786f0` | pluggy._callers · _multicall / _raise_wrapfail / _warn_teardown_exception / run_old_style_hookwrapper behavior | 2 | `src/pluggy/_callers.py`, `testing/test_multicall.py` |
| `zone-proposal_eed637699934e9b210a31aa6` | pluggy._hooks · _call_history / _hookimpls / spec state | 4 | `src/pluggy/_hooks.py` |

## Ownership

| Responsibility | Zone | Mass |
|---|---|---:|
| `responsibility_001f7d3e5e5e63834c334159` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_184ca0300d102ab4c144de3e` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_31f732be614e0ea7fec67a4b` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_363a34ae8159d96ecdaccf8f` | `zone-proposal_ba568823a83486bb12bac355` | 1.0 |
| `responsibility_48b782f7a864cd5f28d75fbf` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_492dce26d66d1529d7db7fc3` | `zone-proposal_eed637699934e9b210a31aa6` | 1.0 |
| `responsibility_4ca6a385a876b0b5ca8ed4f6` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_5a4a68792a93d83aeead0ab8` | `zone-proposal_eed637699934e9b210a31aa6` | 1.0 |
| `responsibility_65f78484aca6dd6976da6de3` | `zone-proposal_45a509d66fbfabba560ed746` | 1.0 |
| `responsibility_730f1ff58b0b35dd722ac5c1` | `zone-proposal_45a509d66fbfabba560ed746` | 1.0 |
| `responsibility_78500e20fc04989c79ee378b` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_83cb28315396b0616896213a` | `zone-proposal_eed637699934e9b210a31aa6` | 1.0 |
| `responsibility_843c1e450c886907cb5273c3` | `zone-proposal_ba568823a83486bb12bac355` | 1.0 |
| `responsibility_98efb364ee7df9c76ed08ecf` | `zone-proposal_45a509d66fbfabba560ed746` | 1.0 |
| `responsibility_a88c00e6d40837f5311d9832` | `zone-proposal_40810f0a418586590a13cc2e` | 1.0 |
| `responsibility_b3f9ee62202901cab14c0a24` | `zone-proposal_eed637699934e9b210a31aa6` | 1.0 |
| `responsibility_b4710d3d1e328168f1d2cb5c` | `zone-proposal_45a509d66fbfabba560ed746` | 1.0 |
| `responsibility_b5af50ca7b04603a35223165` | `zone-proposal_7bcfcb07cc1f9e393bdf783f` | 1.0 |
| `responsibility_ce62b0ac07d218aa90055d64` | `zone-proposal_c9f9e8f5d80d7d34d17786f0` | 1.0 |
| `responsibility_e4089e2c066e39ba318b30f1` | `zone-proposal_53e6797b43aa6423956ae6a4` | 1.0 |
| `responsibility_f165153a11b5c1d9a79e7be7` | `zone-proposal_c9f9e8f5d80d7d34d17786f0` | 1.0 |

## Boundaries

| Source | Target | Mass |
|---|---|---:|

## Runs

| Run | Status | Analysis digest | Proposal digest |
|---:|---|---|---|
| 1 | PASS | `sha256:756b7c68a794cc8cc0a791ed0da2653c82984aa1b8a655dd18f57dcc4d389e07` | `sha256:b81313bea6a79ea5ee7f2e59372842edb81882f90e62d82e1d0695ff22466f36` |
| 2 | PASS | `sha256:756b7c68a794cc8cc0a791ed0da2653c82984aa1b8a655dd18f57dcc4d389e07` | `sha256:b81313bea6a79ea5ee7f2e59372842edb81882f90e62d82e1d0695ff22466f36` |
