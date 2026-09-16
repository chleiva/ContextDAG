# Length Ablation — Handoff (final experiment)

**Type:** controlled ablation on existing validated scenarios. No scenario generation; no LLM writes any conversation text.
**Prepared:** 16 September 2026.
**Budget:** Stage 1 ≈ $5, Stage 2 ≈ $3. Warning $10. Hard limit $15. Stage 2 runs only if Stage 1 finishes under $7.

> This is the last experiment in this project. Whatever it returns, the next deliverable is a paper draft, not another phase. If this run surfaces a new defect, record it in §9 as future work and write the paper anyway.

## 1. What this measures, and why it is cheap

Benchmark 1.2's pilot produced longer *and easier* scenarios, so length was never isolated. This phase varies length and nothing else, by splicing distractor branches from already-validated benchmark 1.1 scenarios into other 1.1 scenarios. The `oracle_dag` context is identical at every length, so Δ(60) − Δ(9) = full_history(9) − full_history(60): one paired quantity, uncontaminated by difficulty drift.

## 2. Construction

Targets: 40 scenarios from 1.1, 8 each from `two_branch_join`, `three_way_join`, `resume`, `long_noisy_side_thread`, `new_root`. Donor pool: every non-gold turn from every other 1.1 scenario, grouped by source branch; donors spliced whole. Donor selection: rank candidate branches by cosine (all-mpnet-base-v2) of the branch text to the target's query; select greedily. Hard exclusion: reject a donor sharing any named entity with the target's gold closure or containing any query entity. Lengths: 9 (original), 30, 60. Interleaving: gold turns keep their order; donor blocks placed before the first gold turn, between gold turns and after the last, one RNG seed per target so 30 is a strict subsequence of 60 and the original of both. Renumber; change no text.

## 3. Pre-flight checks — all free, all before the first billed call

(1) Oracle-context invariance: hash the serialised `oracle_dag` context at 9/30/60; all equal. (2) Entity disjointness for every spliced branch. (3) Donor pool sufficiency to 60 turns for every target. (4) Checklist, query and gold closure byte-identical to 1.1's. If any fails, stop and report.

## 4. Stage 1 — primary measurement (≈ $5)

Arms: `full_history` at 9/30/60 and `oracle_dag` once. Responders Sonnet 4.6, Haiku 4.5, MiniMax M2.5; judge Llama 4 Maverick only. Cluster bootstrap over scenario ids, 10,000 resamples, pinned seed. Report per model and pooled: `full_history(9) − full_history(60)` (primary) with 9→30 and 30→60; `oracle_dag − full_history` at each length; validity diagnostics before interpretation: full-history checklist and distractor leakage by length — leakage must rise with length, otherwise the run is void; retraction rate per arm and length; context tokens.

Interpretation fixed in advance: ≥ +5 pp with CI excluding zero → length amplifies; +2 to +5 pp → directional, under-powered; < +2 pp or negative → full history does not degrade out to 60 turns on this benchmark; the quality claim is closed, as a finding.

## 5. Stage 2 — retrieval at length (≈ $3, only if Stage 1 finished under $7)

`semantic_retrieval@matched` at 9/30/60 (budget = the scenario's `oracle_dag` token count). Report `oracle_dag − semantic_retrieval@matched` at each length with CIs and retrieval's context recall by length.

## 6. Ledger

Stage 1 answers $4.00, judging $1.00; Stage 2 $3.00; estimate $8.00; warning $10 / Stage-2 gate $7 / hard limit $15.

## 7. Scope discipline

Only §§2–5. No generation, no 1.1 modification, no router, no Opus, no added arms.

## 8. Deliverables

`docs/results/LENGTH_ABLATION_RESULTS.md`; the spliced sets under a `length-ablation` tag with the splice script and its assertions; §9 filled in.

## 9. Anything else found

Record as future work; do not fix; do not propose a run.

## 10. What happens after this

The paper is written from what already exists plus this result. Claims in order of strength: (1) retrieval at matched budget is materially worse than structured selection; (2) structural reductions in irrelevant context and leakage; (3) removing irrelevant history helps weak models most; (4) four characterised failure modes of turn-level closures, including retraction, with the provenance mitigation; (5) quality non-inferior, not superior, with the power analysis; (6) this ablation's length result in whichever form it takes. Limitations: oracle router throughout, synthetic benchmark, nine-turn base histories, single-vendor judge calibrated cross-vendor, one sample per cell with 27% decoder variance, and the two documented benchmark defects.
