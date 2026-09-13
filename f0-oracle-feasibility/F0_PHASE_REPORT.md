# ContextDAG — F0 Oracle Feasibility: Phase Report

Written 13 September 2026, at the close of the F0 phase.
Companion to `F0_RESULTS.md` (the numeric report in the handoff's template). This document is the narrative record: what was built, how the run actually went, every decision and deviation, what the numbers mean, and what should happen before F0.5 starts.

---

## 1. Purpose and scope

F0 asked one narrow question before any automatic system was built: **given a perfect, hand-labeled dependency graph over a multi-turn conversation, does building model context from only the query's ancestor closure beat strong existing baselines on the quality-versus-tokens trade-off?** If the ceiling isn't there, no router can reach it.

The pre-registered hypothesis (H1) had three parts, all written into `manifest.yaml` before the full run and never changed afterward:

1. Oracle DAG context reduces average context tokens by at least 40% versus full history.
2. Oracle DAG answer quality is non-inferior to full history, within 5 percentage points or better.
3. Oracle DAG beats the oracle single-parent tree on join-family scenarios (the only place they differ).

Everything in this phase was offline. No router, no candidate generation, no UI.

## 2. Outcome

**GO on both response models.** All three thresholds passed with margin:

| Criterion | Claude Sonnet 4.6 | Claude Haiku 4.5 | Threshold |
|---|---|---|---|
| Context tokens, oracle DAG vs full history | −66.3% | −66.3% | ≥ 40% reduction |
| Checklist quality, oracle DAG minus full history | +2.4 pp, 95% CI [−1.1, +6.3] | +3.5 pp, CI [−0.6, +7.7] | ≥ −5 pp |
| Checklist quality, oracle DAG minus oracle tree, join families only | +0.315, CI [+0.20, +0.43] | +0.328, CI [+0.22, +0.44] | > 0 |

Total spend: $62.27 across 5,451 LLM calls, against a $70 hard limit. Wall-clock from first line of code to final commit: roughly 20 hours, of which about 12 were the judge waiting on Bedrock rate limits.

## 3. Timeline

| When (13–13 Sep 2026) | What |
|---|---|
| Evening, hour 0 | Handoff read; environment checked; no API keys present |
| Hour 0–1 | Provider decision: Bedrock token verified, OpenAI key tested (GPT-6 Astra reachable), cost estimates compared, user chose "option 4" (Bedrock: Sonnet 4.6 + Haiku 4.5 responders, Opus 4.6 judge) |
| Hour 1–2 | Repo scaffold, schema, generator, cost ledger; 10 pilot scenarios generated and hand-read |
| Hour 2 | User asked for a $70 hard stop with a warning at $52, and full resumability; then went to sleep and delegated the rest of the run |
| Hour 2–3 | Pilot defects fixed (signposting, one wrong checklist value); 140 scenarios generated in 26 minutes with 4 workers |
| Hour 3–5.5 | Answer generation: 2,520 instances. One memory kill at 140 instances, fixed by caching embeddings to disk; rerun took 2.1 hours |
| Hour 5.5–18 | LLM judging: 2,520 instances at 5–10 per minute, throttled by Bedrock's Opus quota; two daily-token-cap events; sharded across regions and profiles |
| Hour 18–19 | Cleanup pass, analysis, report, README, four commits pushed to `github.com/chleiva/ContextDAG` |

## 4. What was built

All code is Apache-2.0 under `f0-oracle-feasibility/src/`. The benchmark data under `data/` is CC-BY-4.0. External data: none used.

| Module | Role |
|---|---|
| `schema.py` | Pydantic models for Turn and Scenario; ancestor-closure algorithm (handoff §5.1); the full §3.3 validation checklist as a function, plus a regex check for topic-switch signposting |
| `generate_scenarios.py` | Structure-first generation: 13 family builders decide the gold graph in code from a seeded RNG, then Sonnet 4.6 writes dialogue that realizes that exact outline. Only text and the checklist come from the model. Parallel, resumable, validates and retries |
| `context_methods.py` | The six context methods with one signature. Semantic retrieval selections are precomputed and cached to disk so the long answer run never loads torch |
| `metrics.py` | Precision, recall, F1, sufficiency, token-weighted irrelevant-context ratio; by-construction invariant check |
| `llm.py` | One Bedrock wrapper for every call: streaming, retries, patient 429 backoff, full prompt/response logging, and the cost ledger hook |
| `cost.py` | Spend ledger. Every call is priced from actual usage and appended to `results/raw/cost_ledger.jsonl`; calls refuse to start past the hard limit and warn once past the estimate |
| `run_experiment.py` | scenario × method × budget × model answer generation, keyed and resumable, with a dry-run cost estimator |
| `score_quality.py` | Opus 4.6 judge: checklist verdicts plus distractor leakage; resumable, hash-sharded, model-profile override, fallback prompt for prose responses |
| `analyze.py` | Per-instance and summary tables, paired bootstrap (10,000 resamples), Pareto plot, by-family breakdown, failure-case log, mechanical GO/PIVOT/STOP |
| `write_report.py` | Fills `F0_RESULTS.md` from the tables; no hand-typed numbers |

Reproducing the run from a clean checkout is `manifest.yaml` plus, in order: `generate_scenarios.py --all`, `context_methods.py --precompute`, `run_experiment.py`, `score_quality.py`, `analyze.py`, `write_report.py`. Every stage skips work whose output record already exists.

## 5. Benchmark construction

### 5.1 Method

Per the handoff, the structure is ground truth and must not be reverse-engineered from text. Each family has a builder that emits a list of `(turn_id, gold_parents, role, directive)` from a seed. The LLM receives that outline turn by turn, a premise drawn from 35 non-software-heavy domains, and strict rules: concrete checkable facts in evidence turns, genuinely irrelevant distractors, no signposting, query last with a null assistant message, a 2–4 item checklist with at least one "must not" item, and a reference answer. The assembled scenario keeps the plan's ids, parents, staleness, evidence and distractor sets, and takes only the messages and checklist from the model.

### 5.2 Final composition

140 scenarios, 13 families, every family at its handoff target:

| Family | n | Turns (mean) | Family | n | Turns (mean) |
|---|---|---|---|---|---|
| continuation | 10 | 7.0 | knowledge_update | 12 | 7.2 |
| topic_fork | 10 | 7.8 | ambiguous_reference | 8 | 6.0 |
| resume | 15 | 7.7 | long_noisy_side_thread | 10 | 36.8 |
| new_root | 8 | 7.0 | join_then_split | 10 | 6.6 |
| two_branch_join | 15 | 8.4 | compound_turn | 10 | 7.2 |
| three_way_join | 8 | 10.8 | constraint_retention | 12 | 24.6 |
| semantic_decoy | 12 | 8.0 | | | |

Mean full-history context is 1,388 tokens (cl100k_base); the two long families dominate that mean at 2,781 and 5,197 tokens.

`compound_turn` is the one family whose evidence set is deliberately *not* the ancestor closure: the query depends only on the second half of the compound turn, so evidence is `{t3}` while the closure is `{t1, t2, t3}`. This is recorded per scenario in `evidence_note` and the validator reports it as "reviewed" rather than "flagged". It is the family designed to expose the granularity cost of turn-level selection, and it did (see §8.5).

### 5.3 What the pilot caught

Ten pilot scenarios across four families were generated and read in full. Two defects surfaced:

- **Topic-switch signposting.** Six of ten opened distractor or resume turns with "On a different note", "Separately", "Back to the rail pass", and similar, despite a rule against it. These phrases leak the structure lexically and would have flattered retrieval. Fix: an explicit banned-phrase list in the prompt, plus a regex check in the validator that turns any hit into a validation error and forces a regeneration. All six were regenerated; the full run of 140 passed with 12 of 163 generation calls needing a second or third attempt and one scenario needing four.
- **A wrong checklist number.** One two-branch-join scenario asked for a Shannon diversity index and the generated checklist said ≈1.56; the correct value from the stated counts is 1.44. This would have penalized correct answers. Corrected by hand and noted in the scenario.

Every tenth scenario of the full set (14) was then read in full. No further fixes were needed. Four `ambiguous_reference` scenarios came out at five turns, below the 6-turn floor; the builder was adjusted and they were regenerated.

### 5.4 Cost of the benchmark

163 generation calls, $6.71. Mean call: 1,349 input and 2,473 output tokens. A 36-turn scenario cost about 25 cents; a 7-turn one about 3 cents.

## 6. Models, provider, and cost control

### 6.1 Provider decision

Three options were priced against the same token assumptions before anything ran:

| Configuration | Estimate |
|---|---|
| OpenAI: GPT-6 Astra responder and judge, GPT-5.4-mini second responder | $214 |
| OpenAI: GPT-5.4 and GPT-5.4-mini | $56 |
| Bedrock: Sonnet 4.6 and Haiku 4.5 responders, Opus 4.6 judge (chosen) | $52 |

Bedrock also had a protocol advantage: the Claude 4.6 models accept temperature 0, which the handoff mandates. GPT-6 Astra rejects the temperature parameter and its lowest reasoning effort is `low`, so it could not follow the protocol exactly.

Two Bedrock quirks were found by probing and are recorded in memory and the manifest: this account can reach Sonnet 4.6, Sonnet 4.5, Haiku 4.5, Opus 4.6 and Opus 4.5 but not Sonnet 5, Opus 5, Opus 4.8, Opus 4.7 or Fable; and the SDK's newer Mantle client returns 404 for every model on this account, so the legacy `AnthropicBedrock` client with `us.` or `global.` inference-profile ids is used throughout. The SDK 1.x typed parameters dropped `temperature`; it is passed through `extra_body`.

### 6.2 Final model assignment

| Role | Model | Why |
|---|---|---|
| Response A | Claude Sonnet 4.6 | Strongest reachable mid-tier model |
| Response B | Claude Haiku 4.5 | Weaker model from the same family; no open-weight model was reachable, so this stands in for the "does structure help weaker models more" comparison |
| Judge | Claude Opus 4.6 | Strongest reachable model and distinct from both responders, as the handoff prefers |
| Generator | Claude Sonnet 4.6 | Dialogue quality at moderate cost |
| Embeddings | all-mpnet-base-v2, local | As specified |

### 6.3 Cost guardrail

Added at the user's request before any large run. Prices per model live in the manifest. The ledger is the single source of truth; the dry-run estimator and every progress line read from it. The warning fired at $52.93 as designed; the hard stop at $70 was never reached.

Final accounting:

| Purpose | Calls | Spend |
|---|---|---|
| Scenario generation (Sonnet 4.6) | 163 | $6.71 |
| Answers (Sonnet 4.6 + Haiku 4.5) | 2,521 | $10.98 |
| Rolling summaries (both responders) | 160 | $0.94 |
| Judge (Opus 4.6, both profiles) | ~2,600 incl. fallbacks | $43.61 |
| Debug and smoke calls | 4 | $0.04 |
| **Total** | **5,451** | **$62.27** |

The judge was 70% of the bill. The original $52 estimate assumed 1,300 judge input tokens per call; the actual mean was 1,838 because the judge prompt includes the full text of every distractor turn, and the two long families carry 20–38 of them.

## 7. Protocol as executed

- **Methods.** Full history; sliding window; rolling summary plus recent window (summary written by the responder under test, cached per scenario × budget × model); semantic retrieval with chronological re-sort; oracle tree (primary parent chain); oracle DAG (full closure). Stale turns render with the inline "later revised" marker; the superseder was always in the closure, so no construction issue was flagged.
- **Budgets.** 1,024 and 2,048 tokens for the three budgeted methods (see §10 for why not 2,048/4,096).
- **Response calls.** Fixed system prompt from the handoff, temperature 0, `max_tokens` 2,048. Mean answer length 206 output tokens; no answer hit the cap.
- **Judge calls.** The handoff's checklist rubric verbatim, plus the distractor turns' full text and a distractor-leakage field in the same JSON object. Temperature 0. Score is the fraction of required items satisfied.
- **Statistics.** Paired bootstrap over scenario indices, 10,000 resamples, 2.5th/97.5th percentiles, per response model, never pooled across models.
- **Invariants checked before spending on answers.** Full history recall = 1.0 and oracle DAG sufficiency = 1.0 on all 140 scenarios. Both held.

## 8. Results

### 8.1 Summary (both models)

| Model | Method | Avg context tokens | Token reduction | Checklist score [95% CI] | Precision | Recall | Sufficiency | Irrelevant ratio | Leakage |
|---|---|---|---|---|---|---|---|---|---|
| Sonnet 4.6 | full_history | 1,388 | 0% | 0.858 [0.82, 0.90] | 0.44 | 1.00 | 1.00 | 0.55 | 0.16 |
| Sonnet 4.6 | oracle_dag | 468 | 66.3% | **0.883** [0.85, 0.92] | 0.95 | 1.00 | 1.00 | 0.04 | 0.03 |
| Sonnet 4.6 | oracle_tree | 400 | 71.2% | 0.810 [0.77, 0.85] | 0.95 | 0.90 | 0.84 | 0.04 | 0.03 |
| Sonnet 4.6 | semantic_retrieval@1024 | 871 | 37.2% | 0.869 [0.83, 0.91] | 0.50 | 0.99 | 0.96 | 0.49 | 0.16 |
| Sonnet 4.6 | semantic_retrieval@2048 | 1,093 | 21.2% | 0.877 [0.84, 0.91] | 0.45 | 1.00 | 1.00 | 0.54 | 0.16 |
| Sonnet 4.6 | rolling_summary@1024 | 958 | 30.9% | 0.858 [0.82, 0.89] | 0.41 | 0.77 | 0.66 | 0.57 | 0.16 |
| Sonnet 4.6 | rolling_summary@2048 | 1,130 | 18.6% | 0.851 [0.81, 0.89] | 0.43 | 0.85 | 0.84 | 0.56 | 0.19 |
| Sonnet 4.6 | sliding_window@1024 | 864 | 37.7% | 0.744 [0.69, 0.80] | 0.41 | 0.77 | 0.66 | 0.57 | 0.21 |
| Sonnet 4.6 | sliding_window@2048 | 1,090 | 21.5% | 0.756 [0.70, 0.81] | 0.43 | 0.85 | 0.84 | 0.56 | 0.21 |
| Haiku 4.5 | full_history | 1,388 | 0% | 0.826 [0.78, 0.87] | 0.44 | 1.00 | 1.00 | 0.55 | 0.18 |
| Haiku 4.5 | oracle_dag | 468 | 66.3% | **0.861** [0.83, 0.89] | 0.95 | 1.00 | 1.00 | 0.04 | 0.03 |
| Haiku 4.5 | oracle_tree | 400 | 71.2% | 0.780 [0.74, 0.82] | 0.95 | 0.90 | 0.84 | 0.04 | 0.03 |
| Haiku 4.5 | semantic_retrieval@1024 | 871 | 37.2% | 0.816 [0.77, 0.86] | 0.50 | 0.99 | 0.96 | 0.49 | 0.14 |
| Haiku 4.5 | semantic_retrieval@2048 | 1,093 | 21.2% | 0.828 [0.78, 0.87] | 0.45 | 1.00 | 1.00 | 0.54 | 0.16 |
| Haiku 4.5 | rolling_summary@1024 | 951 | 31.4% | 0.821 [0.78, 0.86] | 0.41 | 0.77 | 0.66 | 0.57 | 0.19 |
| Haiku 4.5 | rolling_summary@2048 | 1,130 | 18.6% | 0.817 [0.77, 0.86] | 0.43 | 0.85 | 0.84 | 0.56 | 0.19 |
| Haiku 4.5 | sliding_window@1024 | 864 | 37.7% | 0.698 [0.64, 0.75] | 0.41 | 0.77 | 0.66 | 0.57 | 0.21 |
| Haiku 4.5 | sliding_window@2048 | 1,090 | 21.5% | 0.701 [0.64, 0.76] | 0.43 | 0.85 | 0.84 | 0.56 | 0.24 |

The Pareto plot (`results/plots/pareto.png`) shows oracle DAG alone in the top-left for both models: the highest checklist score of any method and the second-fewest tokens. Oracle tree is cheaper still but pays for it in quality. Every baseline sits to the right at 2–3× the tokens.

Selection metrics are independent of the response model and confirm the construction: oracle DAG carries 4% irrelevant tokens versus 55% for full history, and its judge-measured distractor leakage is 3% versus 16–18%.

### 8.2 Mandatory pairwise comparisons (oracle DAG minus baseline)

Checklist score, mean difference with 95% CI:

| Baseline | Sonnet 4.6 | Haiku 4.5 |
|---|---|---|
| full_history | +0.024 [−0.011, +0.063] | +0.035 [−0.006, +0.077] |
| sliding_window@1024 | +0.139 [+0.085, +0.196] | +0.163 [+0.106, +0.224] |
| sliding_window@2048 | +0.127 [+0.072, +0.185] | +0.160 [+0.104, +0.220] |
| rolling_summary@1024 | +0.025 [−0.010, +0.061] | +0.040 [−0.004, +0.085] |
| rolling_summary@2048 | +0.031 [−0.003, +0.068] | +0.044 [+0.005, +0.085] |
| semantic_retrieval@1024 | +0.014 [−0.021, +0.049] | +0.045 [+0.000, +0.091] |
| semantic_retrieval@2048 | +0.006 [−0.027, +0.041] | +0.034 [−0.007, +0.076] |

Context tokens, mean difference: −919 vs full history, −396/−622 vs sliding window at 1,024/2,048, −490/−662 vs rolling summary, −403/−625 vs semantic retrieval. All CIs exclude zero by a wide margin.

Reading: oracle DAG is never worse than any baseline on quality, decisively better than the sliding window, and better than every baseline on tokens. Against full history and semantic retrieval the quality difference is small and its CI includes zero, which is exactly what "non-inferior at a third of the tokens" looks like.

### 8.3 The join result

On the 33 join-family scenarios (two_branch_join, three_way_join, join_then_split), oracle DAG beats oracle tree by +0.315 (Sonnet) and +0.328 (Haiku), with CIs bounded well away from zero. By family, Sonnet's checklist score on two_branch_join is 0.95 with the DAG and 0.41 with the tree; on three_way_join 0.69 vs 0.44. The tree's context sufficiency on those families is 0 by construction (it drops every non-primary branch), and the checklists were written so that a single-branch answer fails exactly the items that need the other branch. The multi-parent structure is doing real work.

On join_then_split the two are equal (0.92 vs 0.89), as expected: the query there resumes a single branch and both methods select the same turns.

### 8.4 Checklist score by family

Sonnet 4.6:

| Family | full_history | oracle_dag | oracle_tree | semantic@1024 | rolling@1024 | sliding@1024 |
|---|---|---|---|---|---|---|
| ambiguous_reference | 0.64 | 0.83 | 0.83 | 0.64 | 0.64 | 0.59 |
| compound_turn | 0.79 | 0.70 | 0.68 | 0.82 | 0.79 | 0.78 |
| constraint_retention | 0.89 | 0.97 | 0.97 | 0.97 | 0.92 | 0.38 |
| continuation | 0.82 | 0.82 | 0.82 | 0.78 | 0.85 | 0.82 |
| join_then_split | 0.90 | 0.92 | 0.89 | 0.92 | 0.92 | 0.82 |
| knowledge_update | 1.00 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 |
| long_noisy_side_thread | 0.94 | 0.98 | 0.95 | 0.92 | 0.88 | 0.31 |
| new_root | 0.80 | 0.92 | 0.92 | 0.81 | 0.82 | 0.77 |
| resume | 0.91 | 0.87 | 0.87 | 0.95 | 0.91 | 0.82 |
| semantic_decoy | 0.88 | 0.85 | 0.92 | 0.85 | 0.85 | 0.92 |
| three_way_join | 0.62 | 0.69 | 0.44 | 0.62 | 0.69 | 0.59 |
| topic_fork | 0.78 | 0.90 | 0.90 | 0.80 | 0.80 | 0.78 |
| two_branch_join | 0.97 | 0.95 | 0.41 | 0.98 | 0.92 | 0.92 |

Haiku 4.5:

| Family | full_history | oracle_dag | oracle_tree | semantic@1024 | rolling@1024 | sliding@1024 |
|---|---|---|---|---|---|---|
| ambiguous_reference | 0.57 | 0.92 | 0.92 | 0.57 | 0.57 | 0.60 |
| compound_turn | 0.78 | 0.72 | 0.72 | 0.74 | 0.79 | 0.85 |
| constraint_retention | 0.94 | 0.86 | 0.82 | 0.92 | 0.82 | 0.19 |
| continuation | 0.90 | 0.90 | 0.90 | 0.85 | 0.90 | 0.85 |
| join_then_split | 0.82 | 0.87 | 0.90 | 0.84 | 0.82 | 0.82 |
| knowledge_update | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 |
| long_noisy_side_thread | 0.90 | 0.83 | 0.83 | 0.92 | 0.88 | 0.15 |
| new_root | 0.35 | 0.88 | 0.88 | 0.35 | 0.39 | 0.35 |
| resume | 0.91 | 0.86 | 0.86 | 0.88 | 0.87 | 0.78 |
| semantic_decoy | 0.81 | 0.81 | 0.81 | 0.81 | 0.83 | 0.83 |
| three_way_join | 0.88 | 0.88 | 0.38 | 0.88 | 0.88 | 0.84 |
| topic_fork | 0.78 | 0.82 | 0.82 | 0.78 | 0.88 | 0.80 |
| two_branch_join | 0.88 | 0.88 | 0.40 | 0.85 | 0.86 | 0.87 |

### 8.5 What the family breakdown says

- **Where the DAG helps most: `new_root` and `ambiguous_reference`.** These are the families where the *absence* of history is the correct context. With an empty or single-branch context, Haiku scores 0.88–0.92; with full history it scores 0.35 and 0.57, and its judge-measured leakage on `new_root` with full history is 62%. The weaker model imports irrelevant earlier context whenever it is shown it. This is the clearest evidence for the parent hypothesis that structure helps weaker models more, and it is a *removal* effect, not an *addition* effect.
- **Where the sliding window fails: the two long families.** On `constraint_retention` and `long_noisy_side_thread` the window drops the evidence and the score falls to 0.19–0.38. Rolling summary recovers most of it, semantic retrieval nearly all of it. This is the expected shape and confirms the benchmark's long families are doing their job.
- **Where the DAG does not help: `compound_turn`.** Oracle DAG scores 0.70–0.72 versus 0.78–0.79 for full history. The query needs only the second half of one turn, but the closure drags in the first half's upstream A-branch, so the "context" is mostly about the wrong topic and the checklist's negative item ("must not import an A detail") bites. Turn-level granularity is a real limitation of the current dependency semantics; sub-turn segmentation is the obvious follow-up, outside F0's scope.
- **`knowledge_update` is saturated** at 0.98 for everything. The correction turn is always in-window and every method includes it; staleness handling was not stress-tested by this benchmark's lengths. A version with the correction far from the query, or with the stale value restated in a distractor, would be needed to separate methods.
- **`semantic_decoy` and `resume` slightly favor baselines** on Sonnet (0.85 vs 0.88–0.95). Inspection of the failure cases suggests two things: some resume queries were answerable from the distractor branch's general context too, and several checklist items reward explicitly naming the entity being disambiguated, which the oracle context gives the model no reason to do (see §12). Both make the oracle numbers conservative rather than inflated.
- **`three_way_join` is the hardest family for everyone** (0.62–0.69 on Sonnet). These checklists have three required branch-specific items plus a negative; answers that reconcile two of three branches score 0.67. Room for the strong model to fail even with perfect context is itself informative: sufficiency is necessary, not sufficient.

### 8.6 Failure-case log

- Oracle-DAG context-insufficiency cases: **0**, as required by construction.
- Instances (scenario × model) where full history scored at or above oracle DAG while oracle DAG was below 1.0: **80 of 280**, of which 44 are ties and 36 strict full-history wins. They are spread across all 13 families with no concentration; the paired bootstrap already accounts for them.

## 9. Interpretation

The ceiling exists. With the right structure handed to it, a model answers at least as well from a third of the tokens, and on the join patterns that motivate a DAG over a tree, the DAG is worth about a third of a point of checklist score. The result holds for a strong model and a weaker one, and the weaker model benefits more, particularly by *not* being shown irrelevant history.

What this does not show:

- That the right structure can be *found*. Everything here assumes the gold parents. F0.5 is designed to test whether candidate generation can surface them.
- That the effect is large at realistic scales. Mean full-history context here is 1,388 tokens. The token savings will scale with conversation length; whether the quality relationship holds at 50k-token histories is untested.
- That turn-level dependencies are the right granularity. `compound_turn` is a direct counterexample.
- That a semantic-retrieval baseline is beaten on *quality*. It matches the DAG on checklist score at 1.9× the tokens; the DAG's advantage over retrieval is efficiency and leakage, not correctness, on this benchmark.

## 10. Deviations from the handoff, and why

All were decided and recorded before the affected stage ran.

| Handoff said | What was done | Reason |
|---|---|---|
| Budgets 2,048 and 4,096 | 1,024 and 2,048 | Pilot measured ~800 mean full-history tokens; at 4,096 the windowed baselines would equal full history on ~85% of scenarios and carry no information. Recorded in `manifest.yaml` with the rationale |
| STOP AND CHECK IN after the pilot and after the cost estimate | Checkpoints passed autonomously | The user reviewed the plan and cost estimate, set a $70 hard stop, and explicitly delegated the overnight run: "carry on with all tasks without waiting for me". The checkpoints' substance (schema and generation review; measured cost re-estimate) was still done and is recorded above |
| Open-weight second responder | Haiku 4.5 | No open-weight model was reachable in this environment |
| One judge model id | Same model via two Bedrock inference profiles (`us.` and `global.`) and three AWS regions | Per-region daily token quota on Opus 4.6; 1,590 verdicts via the regional profile, 930 via the global one; the user asked that the global endpoint be used, which the final passes did. Each record names its profile |
| Judge prompt returns a JSON list of checklist verdicts | Returns one object with the checklist list plus a leakage field | The handoff asks for leakage "as an additional structured field"; the rubric text itself is verbatim |
| — | Fallback judge prompt for 27 of 2,520 calls (1.1%) | The primary prompt ends with the answer text and has no system prompt; Opus occasionally continued the conversation instead of scoring it. The fallback wraps the same rubric in a system prompt with a delimited answer. Flagged per record |
| Read every 10th scenario | Done (14 scenarios), plus all 10 pilots twice | — |

## 11. Operational issues and fixes

Each of these is now handled in code and would not recur on a rerun.

1. **Memory kill.** The first answer run held the sentence-transformers model in the long-running process; the host killed it for memory at 140 instances. Fix: `context_methods.py --precompute` embeds every scenario once in a short process and caches the per-budget selections to `results/raw/semantic_selection.json`; the answer run reads the cache and needs 137 MB. The resumable design meant no answers were lost.
2. **Opus rate limits.** This account's Opus 4.6 quota is roughly 5–10 requests per minute per region, plus a daily token cap per region that was hit twice. Fixes, in order: patient exponential backoff on 429 (10 s to 120 s, six retries); two judge shards on different profiles; hash-based sharding so restarted shards never overlap; region hopping (us-east-1 → us-west-2 → us-east-2) when a bucket ran dry. Judging still took ~12 hours.
3. **Judge prose responses.** See §10. The fallback resolved every case on first retry.
4. **A bare-list judge response.** One call returned only the checklist array; handled by routing list-shaped output to the fallback and accepting a bare list with leakage marked unknown if it recurs. It did not.
5. **Concurrent file appends.** Two shards and a later cleanup pass wrote to the same JSONL; analysis de-duplicates by key, keeping the first verdict. Zero duplicates occurred in practice.
6. **One 429 on answer generation** (Sonnet, four workers); retried by the resumable rerun.

## 12. Threats to validity

- **Synthetic benchmark, single generator.** All 140 conversations were written by Sonnet 4.6 against code-fixed graphs. Structure is exact; naturalness and the true irrelevance of distractors are only spot-checked (24 scenarios read in full).
- **Same-vendor judge.** Opus 4.6 judged Sonnet 4.6 and Haiku 4.5. Self-preference is reduced by using a different model, not eliminated. The direction of any bias would affect all methods for a given model equally, so method comparisons within a model are less exposed than absolute scores.
- **Checklist artifact that penalizes oracle methods.** Several `ambiguous_reference` and `semantic_decoy` items reward naming the correct entity *as opposed to* the decoy. With oracle context the decoy is absent, so the model has no reason to name it and can lose the item while answering correctly. This depresses oracle scores relative to baselines, so the reported oracle advantage is conservative.
- **Turn-level granularity.** `compound_turn` shows the cost; other families never bundle requests, so the benchmark under-represents this failure mode relative to real chat.
- **Short scenarios.** 11 of 13 families average under 11 turns. The absolute token savings are modest in this regime; the ratio is what generalizes, if anything does.
- **Tokenizer.** cl100k_base is not Claude's tokenizer. Every method is counted the same way, so ratios are meaningful; absolute counts are not what Bedrock bills.
- **Bootstrap on 140 scenarios.** CIs on the full-history comparison span roughly ±4 pp. The non-inferiority conclusion is robust (the lower bound is −1.1 pp against a −5 pp margin); a claim of strict superiority over full history would not be.

## 13. Recommendation and what comes next

Per the handoff's decision procedure, GO means **proceed to F0.5, the candidate-realism check**, and does not mean build a router. F0 has shown the ceiling; F0.5 must show whether a candidate generator can put the right parents in the pool at all, since that is the step an automatic system depends on and this phase deliberately did not test.

Before F0.5, three cheap improvements to the benchmark would sharpen it:

1. **Sub-turn evidence for `compound_turn`**, or a second compound family where the follow-up targets the *first* half, to measure the granularity cost properly.
2. **A harder `knowledge_update`**: corrections placed 15+ turns before the query, and distractors that restate the stale value, so staleness handling actually separates methods.
3. **Checklist audit for disambiguation items**: rephrase "resolves X not Y" items as "uses X's value" so oracle contexts are not penalized for lacking the decoy.

Two operational recommendations for any later phase on this account: budget wall-clock around the Opus quota (about 5 judgments per minute per region, with a daily cap), and keep every stage keyed and resumable, which is what made a night of throttling and one memory kill a non-event rather than a rerun.

## 14. Artifact index

| Path | What |
|---|---|
| `F0_RESULTS.md` | Numeric report in the handoff's template |
| `F0_PHASE_REPORT.md` | This document |
| `manifest.yaml` | Models, budgets, thresholds, prices, spend limits; the run is reproducible from it |
| `data/scenarios/*.json` | 140 scenarios, CC-BY-4.0 |
| `results/raw/answers.jsonl` | Every rendered prompt, response, token count, latency, and selection metric (17 MB) |
| `results/raw/summaries.jsonl` | 160 rolling summaries with their calls |
| `results/raw/semantic_selection.json` | Cached retrieval selections |
| `results/raw/generation.jsonl` | Every generation attempt with validation outcome |
| `results/raw/cost_ledger.jsonl` | Every billable call with actual usage and price |
| `results/scored/scores.jsonl` | Every judge verdict with per-item reasons and raw judge text (7 MB) |
| `results/tables/summary.csv`, `pairwise.csv`, `by_family.csv`, `per_instance.csv`, `failure_cases.csv`, `decision.json` | Analysis outputs |
| `results/plots/pareto.png` | The headline plot |
| Commits `bbef827`, `ac31d02`, `08b3f87`, `2707009` on `main` | Scaffold, benchmark, run, report |

---

## Addendum: benchmark 1.1 (13 September 2026)

The three fixes recommended in §13 were applied before F0.5, and the affected scenarios were re-run with the same models and judge so that `F0_RESULTS.md` reflects benchmark 1.1 throughout. Cost of the addendum: $10.59 (17 scenarios regenerated, 306 answers, 486 judgments), bringing the phase total to $72.86.

### What changed

| Fix | Change | Scenarios touched |
|---|---|---|
| 1. Compound turns | Added `evidence_spans` to the schema, marking which request within a compound turn the query depends on. Added a `first_request` variant (query follows up on the A half; the B half spawns its own distractor branch). | 10 annotated, 5 new (`compound_turn_011`–`015`); family now 15 |
| 2. Harder knowledge_update | Correction now sits 12–20 turns before the query, and one later distractor casually restates the stale value. | 12 regenerated; mean length 23 turns, was 7 |
| 3. Disambiguation wording | Items of the form "resolves *they* to X (not Y)" rephrased as "applies X's facts; need not name X; must not use Y's". | 10 items in 10 scenarios (8 `ambiguous_reference`, 2 `semantic_decoy`) |

### Effect on the results

| Metric | Benchmark 1.0 (140 scenarios) | Benchmark 1.1 (145 scenarios) |
|---|---|---|
| Oracle DAG token reduction vs full history | 66.3% | 68.8% |
| Oracle DAG − full history, Sonnet 4.6 | +2.4 pp [−1.1, +6.3] | +2.7 pp [−0.8, +6.1] |
| Oracle DAG − full history, Haiku 4.5 | +3.5 pp [−0.6, +7.7] | +2.6 pp [−1.4, +6.8] |
| Oracle DAG − oracle tree, join families | +0.315 / +0.328 | +0.315 / +0.328 (unchanged, no join scenario touched) |
| Verdict | GO / GO | GO / GO |

Family-level effects, Sonnet 4.6 checklist score:

- **knowledge_update now separates methods.** Full history, oracle DAG and semantic retrieval all score 1.00; sliding window at 1,024 tokens drops to 0.22 and at 2,048 to 0.62, because the correction turn now falls outside the window and the restated stale value is inside it. On 1.0 every method scored 0.98. The family finally tests what it was designed to test.
- **compound_turn gap closed.** Oracle DAG 0.77 versus full history 0.78 (was 0.70 vs 0.79). The five first-request variants score well for the oracle because their evidence equals the closure; the ten second-request scenarios keep the granularity penalty. The family now measures both directions of the sub-turn problem.
- **ambiguous_reference did not move as expected.** Oracle DAG went from 0.83 to 0.79 and full history stayed at 0.64 after rephrasing. Reading the new judge reasons: the oracle answers still lose the rephrased item when they hedge ("I don't know which site you mean") rather than apply the branch-A facts, which the rephrased criterion correctly counts as a miss. The original artifact (penalizing an oracle answer for not naming the decoy) is gone; what remains is a real behavior of the response model with short single-branch context. The judge-measured leakage for full history on this family is 62%, so the baseline's 0.64 is not a ceiling effect either.

Token reduction rose from 66.3% to 68.8% solely because the regenerated knowledge_update scenarios are longer; the oracle context for them is unchanged in size (three A turns).

### Bookkeeping

- Manifest: `benchmark_version: 1.1`, `family_targets.compound_turn: 15`, hard spend limit raised from $70 to $82 with the user's approval for this addendum.
- Records for the 27 re-run or re-judged scenarios were purged before re-running; every other record is unchanged from the 1.0 run. All judge calls for the addendum used the global Opus 4.6 inference profile.
- Judge prompt-fallback rate on the full 2,610: 25 (1.0%).
