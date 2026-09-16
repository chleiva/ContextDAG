# Check 3 — Retrieval/Compression Comparability: Execution Plan (awaiting approval)

Prepared 14 September 2026 from `check3-handoof.md`. Analysis pass over existing data plus ~$3 of
cheap-judge and MiniMax calls. Nothing has been computed against the frozen criterion yet; the two
free verification checks (§3.1 of the handoff) have been run and are recorded below.

## 1. Verification checks already done (zero cost)

- **(a) Turn-order diff.** For every pair where `candidate_oracle@15` and `oracle_dag` select the
  same turn set (432 of 435 across Sonnet, Haiku, MiniMax) the serialised prompt is byte-identical.
  No order effect; the F0.5 "near-replication" reading stands as a replication of the *prompt*.
  Only 23 of those 432 identical prompts produced byte-identical answers: temperature 0 on Bedrock
  is not deterministic, which is the mechanism behind the F0.5 per-family noise floor.
- **(b) Off-route judge calls.** All 32 off-route Opus calls (of 731) are in the MiniMax arm:
  9 `candidate_oracle@15`, 10 `full_history`, 13 `oracle_dag`, spread over `us.`@us-east-1,
  `us.`@us-west-2 and `global.`@us-west-2. None touch Sonnet or Haiku. The confirmatory set is
  unaffected; the MiniMax (secondary) arm carries a note.
- **Coverage.** Opus verdicts exist for all four confirmatory baselines × 2 models (F0) and for
  `candidate_oracle@{5,10,15}` × 2 models (F0.5). Llama 4 Maverick covers full_history, oracle_dag,
  oracle_tree, semantic_retrieval@1024, sliding_window@1024 on both models.

## 2. Frozen `check3` section (to be committed before any computation)

```yaml
check3:
  status: confirmatory_with_disclosure     # one point estimate known in advance (handoff §0); everything else blind
  known_in_advance: "pooled candidate_oracle@15 - semantic_retrieval@1024 ≈ +0.028 (from JUDGE_RECALIBRATION_RESULTS enlarged-sample means)"
  primary_judge: opus_4.6_verdicts_on_disk   # F0 + F0.5; zero new Opus calls
  replication_judge: us.meta.llama4-maverick-17b-instruct-v1:0
  primary_models: [response_a, response_b]
  secondary_models: [response_c]
  reference_method: candidate_oracle@15
  confirmatory_baselines: [semantic_retrieval@1024, semantic_retrieval@2048, rolling_summary@1024, rolling_summary@2048]
  non_inferiority_margin: -0.03             # lower bound of the 95% cluster-bootstrap CI on the paired difference
  token_ratio_fail_max: 1.3                 # FAIL: best baseline non-inferior to cand@15 AND tokens <= 1.3x cand@15
  token_ratio_pass_max: 0.7                 # PASS: cand@15 non-inferior to every baseline AND tokens <= 0.7x best-scoring baseline
  unit: scenario                            # cluster bootstrap over scenario ids, 10,000 resamples, per model
  pooled: average_within_scenario_first
  multiple_comparisons: holm_over_4_per_model   # one-sided non-inferiority p-values; unadjusted CIs also reported
  per_family_noise_floor: 0.075             # from F0.5 identical-context arms (sd 0.039, max 0.075)
  exploratory: [candidate_oracle@10 vs baselines, oracle_dag vs baselines, per-family, MiniMax arm, sliding_window]
  budget: {estimate_usd: 3, warn_usd: 5, hard_limit_usd: 10}   # separate ledger results/raw/cost_ledger_check3.jsonl
```

## 3. Work items

1. Freeze §2 in `manifest.yaml`; commit.
2. `src/check3.py`: load F0 + F0.5 answers/scores; paired differences per scenario × model;
   cluster bootstrap (10k) on checklist score and on context tokens (mean diff and ratio);
   Holm-adjusted one-sided non-inferiority verdicts; per-family bootstrap CIs (reusable helper);
   quality/token frontier (mean ± CI on both axes) for every method, per model; precision,
   irrelevant-context ratio, distractor leakage per method in the same table; mechanical decision.
3. Llama second judge on the gaps (§3.3): `candidate_oracle@15`, `semantic_retrieval@2048`,
   `rolling_summary@{1024,2048}` for Sonnet + Haiku, 1,160 calls ≈ $0.81. Verdicts for
   `candidate_oracle@{5,10}` copies inherit as before. Every confirmatory comparison reported under
   both judges; disagreement on the margin side is reported as such.
4. MiniMax M2.5 arm (§3.4, secondary): generate `semantic_retrieval@{1024,2048}` and
   `rolling_summary@{1024,2048}` (580 answers ≈ $1.0; rolling summaries written by MiniMax itself
   per F0's summarizer policy, 290 short calls ≈ $0.15, through the converse backend); judge with
   Llama (≈ $0.41). Also re-judge MiniMax's existing three arms with Llama (435 calls ≈ $0.30) so
   the MiniMax table is single-judge. Off-route note attached.
5. Verbosity check (§3.4): 40 MiniMax `candidate_oracle@15` instances, answers truncated to the
   token length of Haiku's answer on the same scenario, re-judged with Llama alongside the
   untruncated originals (≈ $0.06). Report whether MiniMax's margin over Haiku survives.
6. `docs/results/CHECK3_RESULTS.md` per the F0.5 template with the §0 disclosure verbatim; frontier
   figure at `f05-candidate-realism/results/check3/frontier.png` + CSV; session notes updated.

## 4. Cost

| item | est. |
|---|---|
| Llama re-judging, Sonnet/Haiku gaps | 0.81 |
| MiniMax baselines (answers + summaries) | 1.15 |
| Llama judging of MiniMax (new + existing arms) | 0.71 |
| Verbosity subsample | 0.06 |
| Contingency | 0.50 |
| **Total** | **≈ $3.2** (warn $5, hard $10, zero Opus) |

## 5. Decisions requested

1. MiniMax's Bedrock rate: confirm from the AWS console or keep the $0.60 / $2.40 upper bound.
2. Re-judge MiniMax's existing arms with Llama (+$0.30) for a single-judge MiniMax table (recommended).
3. `docs/results/F0.5_Analysis_and_Recommendations.md` is cited as prerequisite but is not in the repo;
   add it if available (non-blocking; the session notes summarise it).
