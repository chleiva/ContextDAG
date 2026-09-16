# Check 3 — Retrieval/Compression Comparability: Analysis Handoff

**Phase type:** analysis pass over existing data, not a new experimental phase.
**Prepared:** 14 September 2026. Hand this to a fresh Claude Code session with a checkout of `github.com/chleiva/ContextDAG`.
**Prerequisite reading for the executing session:** `docs/results/F0.5_Analysis_and_Recommendations.md` (especially §0 and §7), `docs/results/F0.5_RESULTS.md`, `docs/results/JUDGE_RECALIBRATION_RESULTS.md`, spec v0.4 §12.2.

**Why this is not a new run.** Check 3 asks whether semantic retrieval and summarisation match the *candidate-realistic* oracle's quality/token trade-off. Both sides already exist: F0 scored `semantic_retrieval@{1024,2048}` and `rolling_summary@{1024,2048}` on all 145 scenarios for Sonnet 4.6 and Haiku 4.5; F0.5 produced `candidate_oracle@{5,10,15}`. What is missing is the comparison itself — computed correctly, with the right resampling unit, a second judge, and per-family intervals. Estimated new spend: **~$3**.

---

## 0. Integrity disclosure — read before freezing thresholds

This analysis is **confirmatory-with-disclosure, not blind pre-registration**, and must be described that way in any writeup.

One point estimate is already known. Deriving it from the enlarged-sample contrasts in `JUDGE_RECALIBRATION_RESULTS.md`, pooled over Sonnet and Haiku on benchmark 1.1:

| method | checklist | context tokens |
|---|---|---|
| full_history | 0.838 | 1,508 |
| semantic_retrieval@1024 | 0.841 (derived) | ~900–1,080 |
| oracle_dag | 0.865 | 471 |
| candidate_oracle@15 | 0.869 | 472 |

so `candidate_oracle@15 − semantic_retrieval@1024 ≈ +0.028` pooled. That number was computed before this handoff was written and cannot be un-seen.

**What remains genuinely blind, and is the substance of this pass:** all confidence intervals; the per-family breakdown; `@2048` configurations; both `rolling_summary` budgets; the second-judge replication; the MiniMax arm; and the token-side comparison. Freeze §1's thresholds before computing any of those. Do not adjust them afterwards. Record in the results doc which quantities were known in advance (the one above) and which were not.

---

## 1. Thresholds to freeze before any computation

Write these into `manifest.yaml` under a `check3` section and commit before running anything.

Check 3 is a **trade-off** test, not a quality test. The pre-registered criterion, per spec §12.2:

> Check 3 **fails** (i.e. retrieval/compression is comparable, and the contribution claim narrows to efficiency/leakage/joins) if the best retrieval or compression configuration is non-inferior to `candidate_oracle@15` on checklist score **and** uses no more than 1.3× its context tokens.
>
> Check 3 **passes** (structured context retains a distinct advantage) if `candidate_oracle@15` is non-inferior to every retrieval and compression configuration on checklist score **and** uses ≤ 0.7× the context tokens of the best-scoring one.
>
> Any other outcome is **indeterminate** and is reported as such, not resolved by picking a favourable sub-analysis.

- Non-inferiority margin: **−0.03** checklist points (lower bound of the 95% CI on the paired difference). Tighter than F0's −0.05 because the comparison is against a strong baseline rather than full history; state the choice in the manifest.
- Primary unit of analysis: **the scenario** (n=145), per response model.
- Primary response models: **Sonnet 4.6 and Haiku 4.5** (continuity with F0/F0.5). MiniMax M2.5 is secondary.
- Primary judge: **Claude Opus 4.6** verdicts already on disk. Llama 4 Maverick is the replication judge, not the primary — swapping the primary judge mid-comparison would confound the check.
- Confirmatory comparisons (exactly four, per response model): `candidate_oracle@15` vs each of `semantic_retrieval@1024`, `semantic_retrieval@2048`, `rolling_summary@1024`, `rolling_summary@2048`, on checklist score and on context tokens. Everything else in this document is **exploratory** and must be labelled so.

---

## 2. Statistical requirements

These are the parts most likely to be got wrong, so they are specified rather than left to judgement.

1. **Resample scenarios, not instances.** Every method is evaluated on the same 145 scenarios. A bootstrap over instances treats `(scenario × model)` pairs as independent and will understate the standard error by up to √2. Use a **cluster bootstrap over scenario ids**, 10,000 resamples, matching F0/F0.5's resample count.
2. **Report per-model as primary.** Pooling Sonnet and Haiku is secondary and, when done, must average within scenario *before* resampling, so the cluster count stays 145.
3. **Paired differences only.** Same scenario, same response model, same judge, two methods. Never compare marginal means across arms.
4. **Per-family intervals are mandatory** this time (the F0 review has asked twice). Bootstrap within family. Interpret against the empirical noise floor established in F0.5: **per-family gaps have sd ≈ 0.039 and max 0.075 between arms holding identical context.** Any family-level difference inside ±0.075 is not reportable as signal, whatever its point estimate.
5. **Multiple comparisons.** Four confirmatory comparisons × two models. Report unadjusted CIs plus a Holm-adjusted verdict for the confirmatory set; state both. Do not adjust the exploratory set — label it instead.
6. **Token comparison is paired and reported as both** absolute mean difference and ratio, with the same cluster bootstrap. The trade-off criterion in §1 uses the ratio.

---

## 3. Work items

### 3.1 Two free verification checks — do these first

Both come from `docs/reviews/F0.5_Analysis_and_Recommendations.md` §7 and §0, both are load-bearing for claims already drafted, and both cost nothing.

- **(a) Turn-order diff.** For 10 scenarios where `candidate_oracle@15` and `oracle_dag` select the same turn set, diff the *serialised* contexts byte-for-byte. If they differ only in ordering, the "near-replication" reading in the F0.5 review is an order effect, not a replication, and the `ambiguous_reference` anomaly (identical +0.041 across all three response models) is explained. Report either way.
- **(b) Off-route judge calls.** F0.5 routed 32 of 731 Opus judge calls through a different inference profile/region after the nine-hour quota stall. Group those 32 by `(method, response model)` and report the distribution. If they cluster in one arm rather than spreading, they are a confound and that arm's verdicts need a note.

### 3.2 Compute check 3 on existing data

No new answer generation for Sonnet and Haiku. All arms exist.

- The four confirmatory comparisons per model, per §1–2.
- Exploratory: same comparisons for `candidate_oracle@10`; `oracle_dag` vs the same four baselines (so the oracle-optimistic and candidate-realistic versions can be shown side by side); per-family breakdowns with intervals.
- Report the **full quality/token frontier** — every method as a point in (mean context tokens, mean checklist score) with intervals on both axes. This is the figure the paper needs and no phase has produced it yet.
- Report **context precision, irrelevant-context ratio and distractor leakage** alongside quality for each method. F0 found these are where structure separates most clearly from retrieval (0.95 vs 0.45–0.50 precision; 3% vs 14–16% leakage); if the quality difference is indeterminate, these carry the contribution claim and must be in the same table.

### 3.3 Second-judge replication (~$1)

Llama 4 Maverick already has verdicts on all 1,450 F0 instances for `full_history`, `oracle_dag`, `oracle_tree`, `semantic_retrieval@1024`, `sliding_window@1024`. Score the gaps so the whole check-3 table has dual-judge coverage:

| arm | models | instances | ~cost |
|---|---|---|---|
| `candidate_oracle@15` | A, B | 290 | $0.20 |
| `semantic_retrieval@2048` | A, B | 290 | $0.20 |
| `rolling_summary@{1024,2048}` | A, B | 580 | $0.41 |

Report every confirmatory comparison under both judges. **Agreement between judges on the check-3 verdict is itself a result** — and if they disagree on which side of the non-inferiority margin a comparison falls, say so plainly rather than choosing one.

### 3.4 MiniMax M2.5 arm (~$1.30, recommended)

M2.5 currently has only `full_history`, `oracle_dag`, `candidate_oracle@15`. It is your strongest responder and the only cross-vendor one, so it is the arm where a reviewer will most trust the result. Generate its four missing baselines — `semantic_retrieval@{1024,2048}`, `rolling_summary@{1024,2048}` — 580 answers at ~$0.0015 plus Maverick judging at $0.0007. Secondary/exploratory, not part of the frozen criterion.

**Before quoting any M2.5 quality margin**, run the verbosity check from the F0.5 review §8: M2.5 emits 482 output tokens per answer against Haiku's 201, and checklist scoring rewards coverage. Re-score a 40-instance subsample with answers truncated to a comparable length, and report whether the margin survives. Also confirm its Bedrock per-token rate from the console — the F0.5 ledger billed it at an assumed upper bound.

---

## 4. Decision and reporting

Apply §1's criterion mechanically to the confirmatory set under the primary judge. Then:

- **If check 3 fails** (retrieval comparable): the contribution claim narrows to efficiency, distractor-leakage reduction, interpretability and multi-parent joins, exactly as spec §5.6's fallback anticipated. This is a real and publishable claim. Do not soften it by promoting an exploratory sub-analysis that looks better.
- **If check 3 passes**: state it *conditionally*, because it will not be powered as a pooled superiority claim. With a per-scenario sd of ≈0.21, detecting a ~2.6 pp pooled effect at 80% power needs **≈520 scenarios**; you have 145. Effects around 9–10 pp are powered at n≈40, which is why the conditional results (weak model, small closure) are the ones that show up. Say what is powered and what is not.
- **If indeterminate**: say so, and let §5 below decide what happens next.

Write `docs/results/CHECK3_RESULTS.md` following the F0.5 results template: frozen thresholds quoted, method used, tables, decision applied mechanically, cost ledger, assumptions and limitations. Add the §0 disclosure verbatim.

---

## 5. What this pass does and does not settle

It settles check 3 **on benchmark 1.1** — histories averaging nine turns and ~1,500 full-history tokens, where `semantic_retrieval@1024` retains roughly two-thirds of the conversation and had 0.99–1.0 context recall in F0. That is a regime in which retrieval sees nearly everything the oracle sees, so a null result is weak evidence of comparability and a positive result is a lower bound on the advantage.

**It therefore unblocks router work (R1.1), not the paper.** Benchmark 1.2 — 30–60 turn histories, larger small families, plausible-distractor filler rather than obvious noise — remains required before submission, because "reduces context for long multi-topic conversations" cannot be evidenced on nine-turn conversations. It moves off the critical path, not off the plan.

The natural first router component, and the only one justified before benchmark 1.2, is the **insufficiency detector**: every favourable `candidate_oracle@5` number in F0.5 assumes a system that knows when its candidate pool missed the gold closure, and no such component exists or has been measured.

---

## 6. Ledger

| item | estimate |
|---|---|
| Maverick re-judging (§3.3) | $0.81 |
| MiniMax baselines + judging (§3.4) | $1.30 |
| Verbosity-check subsample (§3.4) | $0.20 |
| Contingency | $0.70 |
| **Warning threshold** | **$5** |
| **Hard limit** | **$10** |

Zero new Opus calls. If any step would exceed the hard limit, stop and report rather than proceeding.

## 7. Deliverables

1. `docs/results/CHECK3_RESULTS.md`
2. Verification notes from §3.1, in that results doc
3. `manifest.yaml` with the frozen `check3` section, committed before any computation
4. Updated `analyze.py` with the cluster bootstrap and per-family intervals (reusable by benchmark 1.2)
5. The quality/token frontier figure, as data plus a plot