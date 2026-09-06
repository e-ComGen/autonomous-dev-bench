# Auto-Zoning preview: requests.pinned_001

> **Advisory only. Authority: NONE. This is not an architectural certification.**

- Commit: `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`
- Source tree: `sha256:27ff0aeea9e531a3eb82144fc5b94c06a772c964e8192dbff0860b62941fc162`
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
| Proposal mass | 0.210950 |
| Partial mass | 0.789050 |
| Unknown mass | 0.000000 |
| Budget exhaustion reasons | 0 |
| Missing obligations | 0 |
| Parse errors | 0 |

## Proposed zones

| Zone | Display name | Responsibilities | Artifacts |
|---|---|---:|---|
| `zone-proposal_3618974b04a700130ee6b5ac` | requests.auth · __call__ / build_digest_header / extract_cookies_to_jar / handle_401 / init_per_thread_state behavior | 2 | `src/requests/auth.py` |
| `zone-proposal_4b119aad98ceb820e7b7526e` | requests · DEFAULT_PORTS / _body_position / _content / _content_consumed state | 8 | `src/requests/_internal_utils.py`, `src/requests/cookies.py`, `src/requests/models.py`, `src/requests/sessions.py`, `src/requests/utils.py`, `tests/test_requests.py`, `tests/test_utils.py` |
| `zone-proposal_5aec5ca7c44a246c96a608d4` | requests.adapters · _pool_block / _pool_connections / _pool_maxsize / config state | 9 | `src/requests/adapters.py`, `tests/test_adapters.py`, `tests/test_requests.py` |
| `zone-proposal_7deb116ca57a1e438839f3d2` | requests.hooks · HOOKS state | 1 | `src/requests/hooks.py`, `tests/test_hooks.py` |
| `zone-proposal_858d6cd47d2a43566eeddb4a` | requests.status_codes · _codes state | 1 | `src/requests/status_codes.py` |
| `zone-proposal_bb9b8607b28f1521c29569a2` | setup · about / requires / test_requirements state | 1 | `setup.py` |
| `zone-proposal_ecabf8b630460c82c035ef3d` | requests · _check_cryptography / check_compatibility behavior | 1 | `src/requests/__init__.py` |

## Ownership

| Responsibility | Zone | Mass |
|---|---|---:|
| `responsibility_01d2d9d8f47a278413aaa3cc` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_0f9801eab4ce4bc1edc59778` | `zone-proposal_7deb116ca57a1e438839f3d2` | 1.0 |
| `responsibility_194770f08e9ea164b0f260f4` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_223c8011d7ec0bed02757f05` | `zone-proposal_858d6cd47d2a43566eeddb4a` | 1.0 |
| `responsibility_329094db751980af8c06fdc4` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_442fc992bdacf29ed459a98e` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_61f5ada81d0fb3a2bb61487a` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_70e7a88c399a4843a5e83f36` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_7211a5176bdb0b59ef822b2a` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_7629a17c15bb07146ed9fd65` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_7d09f8169185da24f9351bf3` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_928e0d852344d63e3468be09` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_a0ceb734a28be8798d2e9020` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_ab4dbbd601d85f0c4b00b9ad` | `zone-proposal_3618974b04a700130ee6b5ac` | 1.0 |
| `responsibility_b0dbe48f1d06d3a087a69944` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_c5e34c3ee17a07721bbcf654` | `zone-proposal_ecabf8b630460c82c035ef3d` | 1.0 |
| `responsibility_c8a5a7c07d351fd31da2fed7` | `zone-proposal_4b119aad98ceb820e7b7526e` | 1.0 |
| `responsibility_cd5f1823fc597c79e1f31f50` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_d578a1600df41e86d5095705` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_dcd3f11ee09e248d3265f1d5` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |
| `responsibility_de087d7077e854453a44de08` | `zone-proposal_3618974b04a700130ee6b5ac` | 1.0 |
| `responsibility_f130cc6d64fd594a762a048e` | `zone-proposal_bb9b8607b28f1521c29569a2` | 1.0 |
| `responsibility_f72a6247830654db5066c5fe` | `zone-proposal_5aec5ca7c44a246c96a608d4` | 1.0 |

## Boundaries

| Source | Target | Mass |
|---|---|---:|

## Runs

| Run | Status | Analysis digest | Proposal digest |
|---:|---|---|---|
| 1 | PASS | `sha256:f374e940e6eede19333090ca6999f8f58e8f50287c78f2f1acb4e4e24486c340` | `sha256:7bc55b0e179849a23bdbb725daec6a0cbda29fc603eaefe6a350a860e63b703d` |
| 2 | PASS | `sha256:f374e940e6eede19333090ca6999f8f58e8f50287c78f2f1acb4e4e24486c340` | `sha256:7bc55b0e179849a23bdbb725daec6a0cbda29fc603eaefe6a350a860e63b703d` |
