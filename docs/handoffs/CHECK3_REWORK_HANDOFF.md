# Check 3 Rework — Handoff

**Type:** correction pass. Five items, all decisions pre-made. Nothing here is open to interpretation — if something seems to need a judgement call, stop and report rather than deciding.
**Prepared:** 15 September 2026. Hand to a fresh Claude Code session with a checkout of `github.com/chleiva/ContextDAG`.
**Read first:** `docs/results/CHECK3_RESULTS.md`, `CHECK3_Analysis_and_Recommendations.md` (external review, not in the repository).
**Budget:** ~$2.15. Warning $4, hard limit $8.

**Scope discipline.** Do items 1–5 and nothing else. Do not re-run the confirmatory comparisons, do not re-open the frozen `check3` criterion, do not "improve" any other analysis you notice along the way. If you find a further defect, write it in §7 and leave it.

## Item 1 — Fix the pooled-row bug (code, no LLM calls)

**Defect.** In `CHECK3_RESULTS.md` §3, the four Opus pooled rows compare a three-model reference mean against a two-model baseline mean. MiniMax M2.5 has Opus verdicts for `candidate_oracle@15` but not for any retrieval or summarisation arm, so it enters the reference average and cannot enter the baselines'. Every Opus pooled delta is inflated by a constant +0.0132. The Llama pooled rows are correct.

**Fix.** Compute the model set as the intersection of models having verdicts for both arms of the comparison, per judge, and use that set for both sides. Regenerate §3's pooled block. Expected corrected Δ (Opus): semantic_retrieval@1024 ≈ +0.0279, semantic_retrieval@2048 ≈ +0.0149, rolling_summary@1024 ≈ +0.0290, rolling_summary@2048 ≈ +0.0362; `semantic_retrieval@2048`'s CI is expected to span zero.

**Regression guard.** Add an assertion, run in the analysis pipeline, that every pooled delta equals the mean of its per-model components to within 1e-6, and that both arms of a pooled comparison used an identical model set.

**Acceptance:** assertion passes; `semantic_retrieval@2048` pooled CI spans zero; the per-model confirmatory table is byte-identical to before.

## Item 2 — Correct the headline and record the criterion defect (text, no LLM calls)

**Defect.** The frozen criterion's FAIL branch was unreachable given the arms in the design: FAIL required a baseline scoring at least as well as the reference while using ≤ 1.3× its context tokens (≤ 614); the cheapest baseline uses 893 (1.89×). Only PASS and INDETERMINATE were reachable.

**Edits:** (1) headline and §4: replace "structured context retains a distinct advantage" with "**PASS (non-inferiority + token ratio).** `candidate_oracle@15` is non-inferior at a −0.03 margin to the best retrieval and summarisation configurations while using 38–53% of their context tokens, with context precision 0.95 vs 0.43–0.49 and distractor leakage 1–4% vs 15–19%."; (2) §10, new bullet recording the unreachable FAIL branch verbatim; (3) §3, replace the judge-agreement sentence with: "Judge agreement: seven of eight confirmatory comparisons agree. The Sonnet INDETERMINATE under Llama rests on a single comparison — vs `semantic_retrieval@1024`, CI low −0.0316 against a −0.0300 margin, missed by 0.0016 — which passes under Holm adjustment. This is a borderline comparison falling on opposite sides of the margin, not a judge-reliability disagreement."

## Item 3 — Variance decomposition on the 432 paired repeats (analysis, no LLM calls)

Compute per response model and pooled: σ²_decoder = var(paired checklist difference over the 432 identical-prompt pairs) / 2; σ²_total = the per-scenario variance used by the cluster bootstrap for `candidate_oracle@15`; σ²_scenario = σ²_total − σ²_decoder; all with bootstrap CIs and the decoder share. Sample-size table for k = 1, 2, 3, 5 samples per cell: σ_eff(k) = √(σ²_scenario + σ²_decoder / k), n = 7.84 · σ_eff(k)² / 0.026². State which lever — more scenarios, more samples per cell, longer histories — buys the most power per dollar. Caveat: σ²_decoder is estimated on one arm only.

## Item 4 — Re-judge the 32 off-route MiniMax instances (~$0.60, Opus)

The one place the no-new-Opus policy is waived, for exactly 32 calls. Re-judge on `global.anthropic.claude-opus-4-6-v1@us-east-1`, recompute the MiniMax `candidate_oracle@15` vs `full_history` row, report old and new side by side.

## Item 5 — `semantic_retrieval@512` sensitivity arm (~$1.55, Llama-judged)

Build `semantic_retrieval@512` contexts for all 145 scenarios with the same retriever; answers for Sonnet 4.6, Haiku 4.5 and MiniMax M2.5; Llama 4 Maverick judging. Exploratory; not added to the frozen confirmatory set; no Opus verdicts. Report `candidate_oracle@15` vs `semantic_retrieval@512` per model with cluster-bootstrap CIs and token ratio; add to the frontier. Interpretation fixed in advance: (a) if `@512` is non-inferior to the reference and within 1.3× its tokens, retrieval is competitive at matched budget and benchmark 1.2 must re-test check 3 with the full budget sweep under a reachable FAIL branch; (b) if `@512` is materially worse, the token-ratio result is strengthened.

## 6. Deliverables

`docs/results/CHECK3_REWORK_RESULTS.md`; `CHECK3_RESULTS.md` updated in place with a dated note; the regression assertion committed; §7 filled in.

## 7. Anything else found

Record, do not fix. Known item to check: Haiku's `three_way_join` scores exactly +0.000 against all five baselines.

## 8. Ledger

Items 1–3 $0; item 4 $0.60; item 5 $1.55; total ≈ $2.15; warning $4, hard limit $8.
