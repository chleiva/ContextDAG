# Check 3 Rework — Results

Run date: 2026-09-15; generated at commit 6a9329b. Scope: the five items of the rework handoff, nothing else. `claude/CHECK3_RESULTS.md` updated in place per items 1 and 2 with a dated note at its top.

## Item 1 — Pooled-row bug

**Defect confirmed.** The pooling routine averaged within scenario over every model with a verdict for *each arm separately*, so MiniMax (Opus verdicts on `candidate_oracle@15` but on none of the retrieval/summary arms) entered the reference mean and not the baselines'. **Fix:** the model set is now the intersection of models carrying verdicts for both arms, per judge, applied to both sides. Before/after:

| judge | baseline | q_diff (old) | q_ci_low (old) | q_ci_high (old) | q_diff (new) | q_ci_low (new) | q_ci_high (new) | pooled_models | shift |
|---|---|---|---|---|---|---|---|---|---|
| opus | semantic_retrieval@1024 | 0.0410 | 0.0134 | 0.0701 | 0.0279 | 0.0003 | 0.0578 | response_a,response_b | -0.0131 |
| opus | semantic_retrieval@2048 | 0.0281 | 0.0013 | 0.0564 | 0.0149 | -0.0132 | 0.0451 | response_a,response_b | -0.0132 |
| opus | rolling_summary@1024 | 0.0421 | 0.0149 | 0.0717 | 0.0290 | -0.0006 | 0.0600 | response_a,response_b | -0.0131 |
| opus | rolling_summary@2048 | 0.0493 | 0.0233 | 0.0782 | 0.0361 | 0.0078 | 0.0670 | response_a,response_b | -0.0132 |
| llama | semantic_retrieval@1024 | 0.0181 | -0.0064 | 0.0443 | 0.0181 | -0.0072 | 0.0444 | response_a,response_b,response_c | 0.0000 |
| llama | semantic_retrieval@2048 | 0.0163 | -0.0077 | 0.0420 | 0.0163 | -0.0079 | 0.0427 | response_a,response_b,response_c | 0.0000 |
| llama | rolling_summary@1024 | 0.0107 | -0.0156 | 0.0383 | 0.0107 | -0.0152 | 0.0379 | response_a,response_b,response_c | 0.0000 |
| llama | rolling_summary@2048 | 0.0136 | -0.0100 | 0.0387 | 0.0136 | -0.0102 | 0.0390 | response_a,response_b,response_c | 0.0000 |

Acceptance: the four corrected Opus deltas match the handoff's expected values (+0.0279 / +0.0149 / +0.0290 / +0.0362 → observed +0.0279 / +0.0149 / +0.0290 / +0.0361); the Opus shift is the constant −0.0132; `semantic_retrieval@2048`'s pooled CI now spans zero; Llama pooled rows are unchanged; the per-model confirmatory table is byte-identical (verified by dataframe equality before regeneration).

**Regression guard** (`src/check3.py`, runs on every analysis): for every pooled row, assert that per-model rows exist for exactly the pooled model set, that all use the same scenario count, and that the pooled Δ equals the mean of the per-model Δs to within 1e-6. It passes on the corrected pipeline and fails on the old one.

## Item 2 — Headline and criterion defect

Applied in `claude/CHECK3_RESULTS.md` (via the report generator, so the edits persist across regeneration): headline and §4 now read **PASS (non-inferiority + token ratio)** with the prescribed sentence; §10 carries the unreachable-FAIL bullet verbatim; the §3 judge-agreement paragraph is replaced by the prescribed text (seven of eight comparisons agree; the Sonnet INDETERMINATE rests on one comparison missed by 0.0016 that passes under Holm). The mechanical verdicts are unchanged. No numeric table was altered.

## Item 3 — Variance decomposition on the 432 identical-prompt pairs

Pairs: `candidate_oracle@15` (F0.5 answer) vs `oracle_dag` (F0 answer) with byte-identical prompts, Opus verdicts on both; 144 pairs per response model. σ²_decoder = var(paired Δ)/2; σ²_total = per-scenario variance of `candidate_oracle@15` (the cluster bootstrap's unit); σ²_scenario = σ²_total − σ²_decoder. 5,000-resample bootstrap CIs.

| arm | n pairs | σ²_decoder | CI | σ²_total | CI  | σ²_scenario | CI   | decoder share | share CI | pairs with equal score |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 144 | 0.0111 | [0.0060, 0.0171] | 0.0373 | [0.0247, 0.0504] | 0.0262 | [0.0122, 0.0404] | 0.2971 | [0.15, 0.54] | 118 |
| Claude Haiku 4.5 | 144 | 0.0106 | [0.0077, 0.0136] | 0.0519 | [0.0383, 0.0649] | 0.0412 | [0.0278, 0.0541] | 0.2052 | [0.14, 0.29] | 105 |
| MiniMax M2.5 | 144 | 0.0106 | [0.0065, 0.0152] | 0.0281 | [0.0175, 0.0417] | 0.0175 | [0.0068, 0.0307] | 0.3767 | [0.22, 0.64] | 113 |
| pooled | 432 | 0.0107 | [0.0082, 0.0134] | 0.0395 | [0.0322, 0.0471] | 0.0288 | [0.0213, 0.0366] | 0.2713 | [0.20, 0.36] | 336 |

Sample size for a 2.6 pp paired effect at 80% power, α = 0.05 two-sided, n = 7.84 σ_eff(k)² / 0.026², σ_eff(k) = √(σ²_scenario + σ²_decoder / k):

| arm | k samples per cell | σ_eff | scenarios needed |
|---|---|---|---|
| Claude Sonnet 4.6 | 1 | 0.193 | 432.859 |
| Claude Sonnet 4.6 | 2 | 0.178 | 368.560 |
| Claude Sonnet 4.6 | 3 | 0.173 | 347.127 |
| Claude Sonnet 4.6 | 5 | 0.169 | 329.980 |
| Claude Haiku 4.5 | 1 | 0.228 | 601.463 |
| Claude Haiku 4.5 | 2 | 0.216 | 539.757 |
| Claude Haiku 4.5 | 3 | 0.212 | 519.188 |
| Claude Haiku 4.5 | 5 | 0.208 | 502.733 |
| MiniMax M2.5 | 1 | 0.168 | 325.475 |
| MiniMax M2.5 | 2 | 0.151 | 264.164 |
| MiniMax M2.5 | 3 | 0.145 | 243.727 |
| MiniMax M2.5 | 5 | 0.140 | 227.378 |
| pooled | 1 | 0.199 | 458.298 |
| pooled | 2 | 0.185 | 396.138 |
| pooled | 3 | 0.180 | 375.418 |
| pooled | 5 | 0.176 | 358.841 |

**Which lever buys power.** Decoder noise is 27% of per-scenario variance (pooled). Repeating each cell k times can remove at most that share: from k=1 to k=5 the required scenario count falls only from 458 to 359 (−22%) while multiplying answer and judge cost by 5. Adding scenarios reduces the standard error as 1/√n with no ceiling, at one answer per cell: reaching the k=1 target of ≈460 scenarios means ≈3.2× the current 145, i.e. ≈3.2× the per-phase answer/judge cost (≈ $1 of Llama judging plus cheap-model answers per 145 scenarios per arm), versus 5× the same cost for a 22% gain from resampling. Longer histories (benchmark 1.2) act on the effect size, not the variance: at the F0/F0.5 effect of ≈2.6 pp none of these options is cheap, whereas an effect of 5 pp needs ≈125 scenarios at k=1 (7.84 × 0.199² / 0.05²) and 9 pp needs ≈38. Per dollar: **longer histories first, then more scenarios, and resampling last.**

Caveat: σ²_decoder is estimated on the `candidate_oracle@15` / `oracle_dag` arm only (the only arm with identical-prompt repeats) and is assumed to transfer to the other arms; that assumption is untested here.

## Item 4 — Re-judged off-route MiniMax instances

32 of 32 instances re-judged on `global.anthropic.claude-opus-4-6-v1@us-east-1` (route recorded per record in `results/scored/check3_rework_opus.jsonl`). 0 of 32 checklist scores changed; mean |change| 0.000.

| version | n | Δ checklist | CI low | CI high | CI excludes 0 |
|---|---|---|---|---|---|
| old (mixed routes) | 145 | 0.0305 | 0.0006 | 0.0621 | True |
| new (all primary route) | 145 | 0.0305 | 0.0017 | 0.0615 | True |

The CI still excludes zero after re-judging. This row is the MiniMax Opus `candidate_oracle@15` vs `full_history` comparison (secondary arm).

## Item 5 — `semantic_retrieval@512` sensitivity arm (exploratory, Llama-judged)

Same retriever, embedding model (all-mpnet-base-v2) and turn-level selection as `@1024`/`@2048`; only the budget changes. 145 answers each for Sonnet 4.6, Haiku 4.5 and MiniMax M2.5, judged by Llama 4 Maverick. Not added to the frozen confirmatory set; no Opus verdicts.

| model | n | Δ checklist (ref − @512) | CI low | CI high | ref NI to @512 | tokens ref/@512 | ratio CI low | ratio CI high |
|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 145 | 0.0555 | 0.0128 | 0.1009 | True | 1.0267 | 0.9414 | 1.1134 |
| Claude Haiku 4.5 | 145 | 0.0318 | -0.0082 | 0.0724 | True | 1.0267 | 0.9420 | 1.1118 |
| MiniMax M2.5 | 145 | 0.0470 | 0.0091 | 0.0861 | True | 1.0267 | 0.9410 | 1.1149 |

Reverse direction (is `@512` non-inferior to the reference at −0.03?):

| model | n | Δ (@512 − ref) | CI low | CI high | @512 NI to ref | tokens @512/ref |
|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 145 | -0.0555 | -0.0998 | -0.0118 | False | 0.9740 |
| Claude Haiku 4.5 | 145 | -0.0318 | -0.0715 | 0.0086 | False | 0.9740 |
| MiniMax M2.5 | 145 | -0.0470 | -0.0861 | -0.0092 | False | 0.9740 |

Frontier row (added to §5 of `CHECK3_RESULTS.md`):

| model | n | tokens | tok_ci_low | tok_ci_high | checklist (Llama) | CI low | CI high | precision | irrelevant ratio | leakage (Llama) |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 145 | 460.041 | 453.559 | 466.531 | 0.824 | 0.782 | 0.864 | 0.718 | 0.272 | 0.124 |
| Claude Haiku 4.5 | 145 | 460.041 | 453.538 | 466.442 | 0.819 | 0.777 | 0.858 | 0.718 | 0.272 | 0.097 |
| MiniMax M2.5 | 145 | 460.041 | 453.469 | 466.517 | 0.865 | 0.827 | 0.900 | 0.718 | 0.272 | 0.124 |

**Interpretation (fixed in advance):** 
Condition (a), `@512` non-inferior to the reference at −0.03 and within 1.3× its tokens: **not met** — the reverse-direction lower CI bounds are Claude Sonnet 4.6 -0.100, Claude Haiku 4.5 -0.071, MiniMax M2.5 -0.086, all below −0.03, at a token ratio of ≈1.0. Condition (b), `@512` materially worse than the reference: the reference's advantage has a CI excluding zero on 2 of 3 models (Claude Sonnet 4.6 +0.056 [+0.013, +0.101], Claude Haiku 4.5 +0.032 [-0.008, +0.072], MiniMax M2.5 +0.047 [+0.009, +0.086]).

Recorded verbatim, since (a) is not met: `@512` is **materially worse than the reference** — retrieval was tried at the oracle's budget and could not match it — so the token-ratio result is strengthened, and benchmark 1.2 still runs the sweep, but without the check-3 conclusion in doubt. Qualification, recorded in §7 rather than resolved here: the handoff's two interpretations did not anticipate a split result; (b) is established on the models whose CI excludes zero and is directional on the remaining one, on which the point estimate favours the reference but the interval includes zero.

## 7. Anything else found (recorded, not fixed)

- **Haiku `three_way_join` +0.000 against all five baselines:** inspected. Not a saturated checklist. Haiku's per-scenario scores vary (1.00, 0.75, 0.25, 1.00, 1.00, 1.00, 1.00, 1.00) but are identical across `candidate_oracle@{5,10,15}`, `full_history`, `oracle_dag`, both `rolling_summary` and both `semantic_retrieval` budgets, and differ only for `oracle_tree` (and one `sliding_window@1024` cell). These eight histories are 8–12 turns, so every one of those contexts contains the entire gold closure, and Haiku returns the same verdict pattern regardless of packaging. `three_way_join_003` scores 0.25 under every context including the oracle: at least one of its required checklist items is not satisfiable by Haiku from any context on this benchmark, which is worth a look when benchmark 1.2 regenerates the family. Sonnet's scores vary across methods on the same scenarios.
- `claude/CHECK3_Analysis_and_Recommendations.md`, listed as required reading, is not in the repository.
- Item 5's two pre-fixed interpretations assume a uniform outcome across models. The observed outcome is split: `@512` fails non-inferiority to the reference on all three models (so (a) is excluded), and the reference's advantage over `@512` has a CI excluding zero on Sonnet and MiniMax but not on Haiku (+0.032 [−0.009, +0.074]). Interpretation (b) was recorded with that qualification; whether Haiku's interval should count as 'materially worse' is a judgement the handoff reserves, and is left here.
- The reported variance-decomposition field previously labelled `identical_answer_pairs` counts pairs with equal *scores* (336 of 432), not identical answers (23 of 432); it is now named `identical_score_pairs`.
- In the F0.5 answer runner, `--dry-run` still triggers rolling-summary generation for models without a cached summary (it does not special-case summaries the way F0's runner did); harmless here because summaries are cached, but a dry run is not free for a new model.

## 8. Ledger

Disclosure: 113 Sonnet/Haiku answer calls in item 5 succeeded on the `global.` inference profile (region fallback under throttling) but were rejected by the ledger, which did not yet know that profile spelling, so they were billed by AWS (≈ $0.51 at the mean answer cost) and neither recorded nor kept; the answers were regenerated after adding the profile prices and a same-model price fallback to `f05_cost.price`.

Rework spend (check-3 ledger, incremental): items 1–3 $0; item 4 $0.66 (32 Opus calls, the sole waiver); item 5 ≈ $1.48 (435 answers incl. the 113 regenerated, plus Llama judging). Check-3 ledger total after rework: **$5.20** (before rework $3.06, so the rework cost $2.14 against its $2.15 estimate); rework warning $4 / hard limit $8 never approached.

| purpose | usd |
|---|---|
| answer | 2.260 |
| check3-judge | 1.962 |
| rework-opus | 0.664 |
| summary | 0.230 |
| check3-verbosity | 0.084 |

| model | usd |
|---|---|
| us.meta.llama4-maverick-17b-instruct-v1:0 | 2.046 |
| minimax.minimax-m2.5 | 1.513 |
| global.anthropic.claude-opus-4-6-v1 | 0.664 |
| us.anthropic.claude-sonnet-4-6 | 0.622 |
| us.anthropic.claude-haiku-4-5-20251001-v1:0 | 0.199 |
| global.anthropic.claude-sonnet-4-6 | 0.122 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | 0.033 |
