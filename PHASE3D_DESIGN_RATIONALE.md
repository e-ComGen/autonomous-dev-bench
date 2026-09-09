# Phase 3D7 — first paid paired experiment design rationale

This document records a pre-experiment design choice. It is not evidence about Stock or ADCP outcomes, and no paid experiment result was consulted.

## Scientific target

The primary endpoint remains `official_swebench_v5_resolved`, the primary estimand remains `paired_difference_in_resolution_rate_adcp_minus_stock`, and the inferential test remains the preregistered two-sided exact McNemar/binomial test at alpha 0.05.

The sensitivity catalog expresses three minimum-detectable paired resolution-rate lifts: 10, 15, and 20 percentage points. These are design thresholds, not predictions of ADCP performance.

For this bounded sensitivity analysis, `expected_discordant_rate=1.0` is used as a conservative maximum-discordance convention. For a desired paired lift delta under that convention, `adcp_win_probability_given_discordance=(1+delta)/2`. This convention intentionally keeps the directional discordant-win probability close to the null and does not claim that all real pairs will be discordant or that it is a theorem of worst-case power for every possible data-generating process.

All scenarios target 80% power and search at most 100 equal repeats per task. No outcome-derived prior is used.

## Sensitivity result expected from accepted D4/D5 exact calculation

For the fixed 10-task cohort:

| MDE | ADCP win probability among discordant pairs | Repeat/task | Total pairs | Total arm runs |
| --- | ---: | ---: | ---: | ---: |
| 10 pp | 0.550 | 81 | 810 | 1620 |
| 15 pp | 0.575 | 37 | 370 | 740 |
| 20 pp | 0.600 | 21 | 210 | 420 |

The repository tooling, not this prose table, is authoritative for the exact achieved power and generated schedule.

## Selected design

Select `mde-15pp-conservative-discordance`.

Reason: 10 pp substantially increases the experiment from 740 to 1620 arm runs, while 20 pp would deliberately give up sensitivity to a moderate 15–20 pp paired lift. The 15 pp design is the pre-experiment compromise between statistical sensitivity and bounded execution cost. This is an operator/research-design tradeoff and is not based on observed Stock or ADCP success rates.

The selected design is expected to compile to:

- 37 repeats per task;
- 370 completed pairs;
- 740 total arm runs;
- fixed-pairs stopping only;
- no outcome-based resizing or stopping.

## Resource caps

Per arm:

- total model tokens: 262,144;
- input tokens: 262,144;
- output tokens: 65,536;
- model requests: 16;
- wall time: 600 seconds;
- patch bytes: 262,144.

The request, output, wall-time, and patch envelopes preserve the earlier operator configuration in `fix/fast-pinned-acquisition` (`AB.toml`: 16 requests/arm, 4096 output tokens/request, 600 seconds/arm, 262144 max patch bytes). The previous path did not have an exact hard input-token cap, so the 262,144 total/input token ceiling is a new explicit experiment-design choice rather than reconstructed historical evidence.

The primary total-token cap dominates component consumption: an arm cannot spend 262,144 input tokens and 65,536 output tokens simultaneously because `total_model_tokens` is capped at 262,144.

At 740 arm runs the aggregate ceilings are therefore:

- 193,986,560 total model tokens;
- 193,986,560 input-token component ceiling;
- 48,496,640 output-token component ceiling;
- 11,840 requests;
- 444,000 aggregate arm-seconds (123.33 hours; elapsed time may be lower with parallel execution);
- 193,986,560 patch bytes.

## Informational API-price envelope

Pricing is not a grading or stopping authority and can change. Using the DeepSeek public pricing snapshot checked on 2026-09-09 for `deepseek-v4-flash` (cache-miss input $0.22/M and output $0.66/M off-peak; $0.44/M and $1.32/M peak), the maximum cost under the token caps is approximately $0.08651 per arm off-peak or $0.17302 per arm peak when the full output cap is consumed and the remaining total-token budget is cache-miss input. Across 740 arms that is approximately $64.02 off-peak or $128.03 peak. Actual spend can be lower and these dollar figures are not an enforced dollar cap.

Pricing reference at decision time: `https://api-docs.deepseek.com/quick_start/pricing`.

## Locks and remaining gates

Locking this design must not reclassify external admission gates. After the design is committed as LOCKED:

- DeepSeek live prompt-token parity must still independently PASS;
- the exact pinned private ADCP runtime must still independently PASS;
- the shared budget proxy and all existing causal controls remain mandatory;
- `PAID_PAIRED_AB` remains `NOT_RUN` until actual execution;
- `winner` remains `UNKNOWN` until the complete preregistered paired analysis is available.
