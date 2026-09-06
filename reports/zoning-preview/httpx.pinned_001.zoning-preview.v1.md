# Auto-Zoning preview: httpx.pinned_001

> **Advisory only. Authority: NONE. This is not an architectural certification.**

- Commit: `26d48e0634e6ee9cdc0533996db289ce4b430177`
- Source tree: `sha256:be11d32cc168136e4cdab82b0a47e8ca3c397dfc7c9caccf92cb1bd3161f5326`
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
| Proposal mass | 0.116992 |
| Partial mass | 0.883008 |
| Unknown mass | 0.000000 |
| Budget exhaustion reasons | 0 |
| Missing obligations | 0 |
| Parse errors | 0 |

## Proposed zones

| Zone | Display name | Responsibilities | Artifacts |
|---|---|---:|---|
| `zone-proposal_0055f1330158f6f9a2bc7393` | httpx._decoders · buffer / decompressor / first_attempt / seen_data state | 4 | `httpx/_decoders.py` |
| `zone-proposal_06c20704d180414ecd6fb627` | httpx._models · SENSITIVE_HEADERS / SUPPORTED_DECODERS / _content / _cookies state | 23 | `httpx/_models.py` |
| `zone-proposal_201bb4679f5ea9d4a061852f` | httpx._urls · _dict state | 2 | `httpx/_urls.py` |
| `zone-proposal_286e8b6970893dbafda8c223` | httpx._utils · get_environment_proxies / is_ipv4_hostname / is_ipv6_hostname behavior | 1 | `httpx/_utils.py`, `tests/test_utils.py` |
| `zone-proposal_28f6dd9005e0d1ec9955c335` | httpx._main · download_response / format_certificate / main / print_request_headers / print_response behavior | 2 | `httpx/_main.py` |
| `zone-proposal_42a04381af5d24e4c383784c` | httpx._auth · _last_challenge / _nonce_count state | 3 | `httpx/_auth.py` |
| `zone-proposal_4b61dd8bc7ff984863a3ebca` | httpx._urlparse · COMPONENT_REGEX state | 1 | `httpx/_urlparse.py`, `tests/models/test_whatwg.py` |
| `zone-proposal_4d7df2a3d5a806f47b009f15` | httpx._exceptions · _request state | 1 | `httpx/_exceptions.py` |
| `zone-proposal_527664188508ee17708c3a42` | httpx._content · _is_stream_consumed state | 4 | `httpx/_content.py` |
| `zone-proposal_64aa8369ce19ed8af85022b0` | httpx._client · SUPPORTED_DECODERS / _auth / _base_url / _cookies state | 23 | `httpx/_client.py` |
| `zone-proposal_8e5e993f529ea8e51bb20159` | httpx · __all__ state | 1 | `httpx/__init__.py` |
| `zone-proposal_cf85f294b337cb23bd405adf` | httpx._multipart · _HTML5_FORM_ENCODING_REPLACEMENTS / _data / _headers state | 8 | `httpx/_multipart.py` |
| `zone-proposal_f7c0b032e425695cc79ecea7` | httpx._transports.default · HTTPCORE_EXC_MAP state | 1 | `httpx/_transports/default.py` |

## Ownership

| Responsibility | Zone | Mass |
|---|---|---:|
| `responsibility_09d0ba0967ccabd7c6bf1cf0` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_0ad71c861c5013d3bb8debc2` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_0f7a91532b539f35e6bb0fba` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_16fd11dbd83f6ca0a8b7c42b` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_19b2fabc2328f047845fe3a0` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_1e9947c359b0ed4f953edffa` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_267599215c1a0efe7559e95f` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_27b02f6630bb6fb3ce409376` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_2eda41182d7c7fd2d7f7b490` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_30ef52b2be067026640d8e92` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_33e7a2caad0e4502d3ce6540` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_3ae1948b18ea1ef2fccef6f8` | `zone-proposal_0055f1330158f6f9a2bc7393` | 1.0 |
| `responsibility_3d142646e9bae48de1e0b561` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_3d2f90ca8a7cc673f925e732` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_4534be9b92dde9e1ef56bdbd` | `zone-proposal_42a04381af5d24e4c383784c` | 1.0 |
| `responsibility_465af2fb68994e5c46d1008c` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_47381280f9d9a0916474371a` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_4a76f6ed69b700382d59b4c8` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_4c570f341d87dccc998459cb` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_4f776b0d2288a240df22d1a6` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_559319715a6cbdab82cde16b` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_56a305a44803d0ed385bfb9b` | `zone-proposal_286e8b6970893dbafda8c223` | 1.0 |
| `responsibility_5c6b75567ca51a41b1c15b25` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_5d25031c63997c4590225734` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_60e51ca286e1ed21b54fc367` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_6461f8996cdfa9238fc6b65d` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_64efe4011357af0594874273` | `zone-proposal_527664188508ee17708c3a42` | 1.0 |
| `responsibility_6645128b76a462a79e126e10` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_6db08a12fb6420835d8c8c76` | `zone-proposal_28f6dd9005e0d1ec9955c335` | 1.0 |
| `responsibility_74b1583714b68345ba43c27c` | `zone-proposal_8e5e993f529ea8e51bb20159` | 1.0 |
| `responsibility_761fd157b4741160d50c7f6b` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_7a8cd4af52aa5969207350a4` | `zone-proposal_527664188508ee17708c3a42` | 1.0 |
| `responsibility_7f37b4bbcecda8c495d015bc` | `zone-proposal_4b61dd8bc7ff984863a3ebca` | 1.0 |
| `responsibility_826581e32f1c5dadae73d28c` | `zone-proposal_201bb4679f5ea9d4a061852f` | 1.0 |
| `responsibility_84b41890a0eaf85da0a51990` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_84f029be99ec61616c711f73` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_8785bb6d34b9b5f137516925` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_8d6c26d94ce8d4d4926070c5` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_8efb6289e6ec8d9194f9eca6` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_9052fdc88a856167e24b8a01` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_930c48863fafd19a34073758` | `zone-proposal_0055f1330158f6f9a2bc7393` | 1.0 |
| `responsibility_93d308298518ef08c113d9a8` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_95f08cc9175794e105084374` | `zone-proposal_0055f1330158f6f9a2bc7393` | 1.0 |
| `responsibility_9875381d0f93a2e242e36ad4` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_9921fa2c4cad288d08cbdc5b` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_99b16348856db6112c783d68` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_9a1bb25ce4da362b17525571` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_9c9e7f098d333df1f8d2826b` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_9edffbc26612faf6aaceb99a` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_a0d3db8c66c9334bc3f5ca25` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_a1603b5642d2593a97b08934` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_a29e01d5c05e1e24991bb950` | `zone-proposal_0055f1330158f6f9a2bc7393` | 1.0 |
| `responsibility_a35254553b78731692719cb2` | `zone-proposal_28f6dd9005e0d1ec9955c335` | 1.0 |
| `responsibility_a5892ae865da38b33482ed7e` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_aaad676437a10305f03b6c8e` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_acee283522cc230e1a1f3e52` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_b21f07c2739c3d16cbc6efcd` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_b2e12a725d593b4c9938c68c` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_c5449ba3fc7ecc81eb4c594a` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_c73bc1b6e4950b9f0e270f94` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_cc9214b33767a4454670a540` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |
| `responsibility_cff8d52a56ca8c1e6431ba1e` | `zone-proposal_42a04381af5d24e4c383784c` | 1.0 |
| `responsibility_d03e016dfe60a899c82b430a` | `zone-proposal_42a04381af5d24e4c383784c` | 1.0 |
| `responsibility_d2d67b3d40b37b7e13ed9255` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_d61089d278f129cd2f218309` | `zone-proposal_527664188508ee17708c3a42` | 1.0 |
| `responsibility_dcdaa74271b697bb8789baa5` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_dd714e4764797af75794ff83` | `zone-proposal_201bb4679f5ea9d4a061852f` | 1.0 |
| `responsibility_debac4864aab3182efb16706` | `zone-proposal_06c20704d180414ecd6fb627` | 1.0 |
| `responsibility_e639bee562fc65f74421c8df` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_e7a3c338ac94be73995782f4` | `zone-proposal_527664188508ee17708c3a42` | 1.0 |
| `responsibility_ef243ffb87b83ee0cecfe00f` | `zone-proposal_4d7df2a3d5a806f47b009f15` | 1.0 |
| `responsibility_f04d450b54b1fa9deefdf510` | `zone-proposal_f7c0b032e425695cc79ecea7` | 1.0 |
| `responsibility_f5b7dcdc2a4f371b7c074768` | `zone-proposal_cf85f294b337cb23bd405adf` | 1.0 |
| `responsibility_fdd3e8d754e86060d193769f` | `zone-proposal_64aa8369ce19ed8af85022b0` | 1.0 |

## Boundaries

| Source | Target | Mass |
|---|---|---:|

## Runs

| Run | Status | Analysis digest | Proposal digest |
|---:|---|---|---|
| 1 | PASS | `sha256:c4ac16c347a81999d953e594f62d4a7610a80527fcaeb6b7d86f03c3db78b692` | `sha256:03d54a3cd0644b90d0ed9726f9f0b0212407f85fd3f089666c5253df8046f1da` |
| 2 | PASS | `sha256:c4ac16c347a81999d953e594f62d4a7610a80527fcaeb6b7d86f03c3db78b692` | `sha256:03d54a3cd0644b90d0ed9726f9f0b0212407f85fd3f089666c5253df8046f1da` |
