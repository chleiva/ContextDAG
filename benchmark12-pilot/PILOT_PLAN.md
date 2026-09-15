# Benchmark 1.2 — Stage A (Length Pilot): Execution Plan (awaiting approval)

Prepared 15 September 2026 from the Stage A handoff. Scope: 40 long scenarios, four arms, three
responders, one number, stop. Nothing billed until the gate is committed.

## 1. Layout

New sibling directory `benchmark12-pilot/` (F0, F0.5 untouched; benchmark 1.1's 145 scenarios never
modified):

```
benchmark12-pilot/
  manifest.yaml            frozen benchmark12_pilot gate (§5 of the handoff), models, prices, budget $20/$35/$50
  data/scenarios/          40 long scenarios, ids long_<family>_NNN, benchmark_version "1.2-pilot", length_class "long"
  src/generate_long.py     long-scenario builders + entity/near-miss/no-filler constraints + §3.1 assertions + cosine gate
  src/run_pilot.py         four arms × three responders (reuses F0 context methods via the F0.5 bridge and client)
  src/analyze_pilot.py     cluster bootstrap, per-comparison pinned seeds, gate applied mechanically
  src/write_pilot_report.py -> claude/BENCHMARK_1.2_PILOT_RESULTS.md
  results/                 raw answers, Llama scores, own cost ledger
```

The shared `schema.py` gets one optional field, `length_class` (default null), so 1.1 files are
unchanged on disk.

## 2. Generation design (§2–3.1 of the handoff)

Structure is decided in code before any text, as in 1.1:

- **Gold structure per family** as in 1.1's builders, with longer chains (3–6 turns per gold branch).
- **Distractor branches**: 3–6 per scenario, all inside the same premise/domain as the gold branch,
  each 3–8 turns, each with a directive to develop a *related* sub-problem of the same project; every
  turn belongs to a branch (no filler by construction) and is interleaved with the gold branches.
- **Entity registry**: the writer must introduce 4–6 named entities (people, products, places,
  documents, versions) in the gold branch and reuse ≥2 of them in *every* distractor branch. The
  prompt receives this instruction; the assertion checks it on the text (spaCy NER + exact string
  match, case-insensitive).
- **Near-miss**: one designated distractor turn per scenario whose directive is "ask a question that
  sounds like the target query but concerns a different entity/version/date, and get a confident
  answer". Asserted present (the writer returns its id) and cosine-checked (≥ gold median × 0.6).
- **Length**: history 30–60 turns drawn uniformly per scenario (median ≈45), target 5,000–8,000
  full-history tokens; token count asserted ≥ 4,000 after generation.
- **Checklist assertions**: the writer returns, per checklist item, the turn ids that satisfy it.
  Asserted: (1) satisfiability — every required item's turns are non-empty and inside the gold
  closure; (2) discrimination (join families) — the required items' turns span ≥2 parent branches;
  (3) closure ratio recorded per scenario, median target ≤ 0.35 reported.
- **Cosine gate** (all-mpnet-base-v2, query vs each history turn): median distractor cosine ≥ 0.60 ×
  median gold-closure cosine. Computed at generation; a failing scenario is regenerated (≤3
  attempts). **Reported two ways:** first-attempt pass rate (the honest instrument reading, since
  retries would otherwise hide a separability problem) and final-set pass rate. If the first-attempt
  rate is < 80% the pilot stops before §4, per the handoff.
- **Families**: two_branch_join, three_way_join, resume, long_noisy_side_thread, new_root; 8 each.
  Builders are parameterised so Stage B can add compound_turn, ambiguous_reference and semantic_decoy
  without regenerating.

Generation is one call per scenario (≈2k tokens in, 6–9k out), up to 3 attempts with the validator's
reasons fed back, as in 1.1.

## 3. Arms, models, judge, statistics (§4)

| arm | context |
|---|---|
| full_history | all history turns |
| oracle_dag | gold ancestor closure |
| semantic_retrieval@matched | F0's retriever, budget = that scenario's oracle_dag token count (per scenario) |
| semantic_retrieval@1024 | F0's retriever at 1,024 |

Responders per the handoff: Sonnet 4.6, Haiku 4.5, MiniMax M2.5 (see decision 2). 480 answers.
Judge: Llama 4 Maverick only. Statistics: paired differences per scenario × model, cluster bootstrap
over scenario ids, 10,000 resamples, **one `default_rng` per comparison seeded from (seed, model, a,
b)** so tables are byte-identical regardless of evaluation order; pooled = average within scenario.

## 4. Gate (frozen in the manifest before the first billed call, verbatim from §5)

Primary: `oracle_dag − full_history` paired checklist difference per model on the 40 long scenarios,
point estimate with 95% cluster-bootstrap CI, plus pooled.
AMPLIFIES: ≥ 5 pp on at least two of three models. PARTIAL: 4–5 pp on at least two of three.
FLAT: < 4 pp on two or more. Anything awkward is reported as awkward. Also reported in all cases:
`oracle_dag − semantic_retrieval@matched` per model; mean context tokens and ratios; closure/history
distribution; precision, irrelevant-context ratio, distractor leakage per arm; the cosine gate
distribution. Standard error at n=40 ≈ 0.032; stated as a scoping instrument, not evidence.

## 5. Cost

| item | est. (Kimi generator) | est. (Sonnet generator) |
|---|---|---|
| Generation, 40 scenarios, ≤3 attempts, ~8k output each | $3 | $10 |
| Answers: Sonnet 160 / Haiku 160 / MiniMax 160 at ~6.5k context | $3.5 / $1.2 / $0.9 | same |
| Llama judging, 480 at long context | $1.0 | same |
| Contingency | $2 | $2 |
| **Total** | **≈ $12** | **≈ $19** |

Own ledger: estimate $20, warning $35, hard limit $50 (handoff §7). Zero Opus.

## 6. Decisions requested

1. **Generator model.** 1.1 used Sonnet 4.6. Recommend **Kimi K2.5** (`moonshotai.kimi-k2.5`): strong
   long-form writer, 256k context, cross-vendor from every responder, ≈$0.03 per attempt vs ≈$0.12
   for Sonnet, and consistent with the no-Anthropic policy. Fallback GLM-5 if Kimi's JSON discipline
   fails on 45-turn outputs.
2. **Responders.** The handoff specifies Sonnet 4.6 + Haiku 4.5 + MiniMax M2.5 for continuity with
   F0/F0.5/check 3 (≈$4.7 of Anthropic spend). Confirm, or drop Sonnet/Haiku and run MiniMax plus two
   cheap models (DeepSeek V3.2, Kimi K2.5), which loses the short-vs-long contrast on the models the
   earlier phases measured.
3. Adding the optional `length_class` field to the shared schema (no change to 1.1 files).
