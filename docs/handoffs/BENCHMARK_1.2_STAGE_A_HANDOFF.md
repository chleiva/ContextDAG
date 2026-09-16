# Benchmark 1.2 — Stage A (Length Pilot): Handoff

**Type:** scoping pilot with a hard stop. Generate 40 long scenarios, measure one number, report, stop.
**Prepared:** 15 September 2026.
**Budget:** estimate $20, warning $35, hard limit $50.

**Scope discipline.** Stage A only. Do not generate the rest of benchmark 1.2. Do not modify any benchmark 1.1 scenario. Do not run the router.

## 1. Why this pilot exists

Every remaining plan rests on one unmeasured assumption: that longer conversation histories increase the effect size of structured context. Benchmark 1.1's histories average nine turns; the pooled `oracle_dag − full_history` effect there is ≈2.6 pp. From the check-3 rework's variance decomposition, the scenarios needed for 80% power at α = 0.05 are 458 at 2.6 pp, 194 at 4 pp, 124 at 5 pp, 38 at 9 pp. This pilot measures the effect at length once, cheaply, before committing to a full generation run. At n = 40 the standard error is ≈ 0.032; the pilot resolves the effect to roughly ±6 pp and is a scoping instrument, not evidence.

## 2. What to generate

40 scenarios, 8 each in `two_branch_join`, `three_way_join`, `resume`, `long_noisy_side_thread`, `new_root`. History length 30–60 turns, median ≈ 45, target 5,000–8,000 full-history tokens. Additive to benchmark 1.1; new ids; `length_class: long`; version the combined set 1.2-pilot.

## 3. Filler realism

Non-negotiable constraints, asserted at generation time: (1) every distractor branch shares at least two named entities with the gold branch; (2) distractor branches stay in the same subject domain; (3) at least one near-miss turn per scenario; (4) no filler turns. Validation gate: median cosine (all-mpnet-base-v2) of distractor turns to the query ≥ 0.60 × median cosine of gold-closure turns; report per family and the fraction passing; if fewer than 80% pass, stop and report.

### 3.1 Gold-closure and checklist assertions

(1) Satisfiability: every required checklist item is satisfiable from the gold closure alone; (2) discrimination: for join families no single parent branch satisfies every required item; (3) record `|closure| / |history|`, target median ≤ 0.35. Do not retro-patch any 1.1 scenario.

## 4. What to run

Four arms: `full_history`, `oracle_dag`, `semantic_retrieval@matched` (budget = the scenario's `oracle_dag` token count), `semantic_retrieval@1024`. Responders Sonnet 4.6, Haiku 4.5, MiniMax M2.5 (480 answers). Judge Llama 4 Maverick only; no Opus. Cluster bootstrap over scenario ids, 10,000 resamples, pinned seed.

## 5. The gate — frozen before any generation

Primary: `oracle_dag − full_history` paired checklist difference per response model on the 40 long scenarios. AMPLIFIES: ≥ 5 pp on at least two of three models → Stage B ≈ 130 long scenarios. PARTIAL: 4–5 pp on at least two → stop and report (≈ 200 scenarios would be needed; a budget decision for the owner). FLAT: < 4 pp on two or more → stop; benchmark 1.2 becomes ≈ 60–80 long scenarios for the efficiency and leakage claims. Anything awkward is reported as awkward. Also report `oracle_dag − semantic_retrieval@matched`, tokens and ratios, the closure/history distribution, precision / irrelevant ratio / leakage per arm, and the cosine distribution.

## 6. Deliverables

`docs/results/BENCHMARK_1.2_PILOT_RESULTS.md`; the 40 scenarios under a `1.2-pilot` tag with the assertions in the pipeline; the frozen `benchmark12_pilot` manifest section committed before any billed call; pinned bootstrap seed; §8 filled in.

## 7. Ledger

Generation $10, answers $6, judging $1.50, contingency $2.50; estimate $20; warning $35, hard limit $50.

## 8. Anything else found

Record; do not fix.

## 9. What Stage B will need (do not do it now)

Same five families plus `compound_turn` (first-request arm), `ambiguous_reference`, `semantic_decoy`; the full retrieval budget sweep (256 / 512 / 1024 / 2048 / matched) under a criterion whose FAIL branch is reachable.
