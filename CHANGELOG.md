# Changelog

All dates 2026. Each entry names the phase, its results document, and its git tag where one exists.

## 0.1.0 — 16 September

- **Length ablation** (`length-ablation/`, tag `length-ablation`): controlled splice of validated
  distractor branches to 30 and 60 turns. Void under its frozen validity rule (leakage fell with
  length); recorded as a negative observation about constructing long-history difficulty.
  `docs/results/LENGTH_ABLATION_RESULTS.md`.
- **Benchmark 1.2 Stage A pilot** (`benchmark12-pilot/`, tag `1.2-pilot`): 39 long scenarios;
  gate verdict FLAT; discovered the *retraction* failure mode (pruned context makes Anthropic
  responders disown assistant-stated facts). `docs/results/BENCHMARK_1.2_PILOT_RESULTS.md`.
- **Check 3 rework**: pooled-row bug fixed with a regression guard; PASS relabelled; variance
  decomposition; off-route re-judging; `semantic_retrieval@512` sensitivity arm.
  `docs/results/CHECK3_REWORK_RESULTS.md`.

## 15 September

- **Check 3** (retrieval/compression comparability): PASS on both primary response models under
  the frozen non-inferiority-plus-token criterion; Llama replication PASS for Haiku, indeterminate
  for Sonnet on one comparison. `docs/results/CHECK3_RESULTS.md`.

## 14 September

- **Judge recalibration**: nine cheap judges calibrated against Opus 4.6; bar v2 (method-contrast
  error); Llama 4 Maverick adopted as the standing judge on a 1,450-instance sample.
  `docs/results/JUDGE_RECALIBRATION_RESULTS.md`.
- **F0.5 candidate realism**: non-LLM candidate generator, Recall@k sweep, candidate-restricted
  oracle; PASS on both models. `docs/results/F0.5_RESULTS.md`.
- Region and inference-profile fallback added to every Bedrock call path; routes recorded per call.

## 13 September

- **F0 oracle feasibility**: benchmark 1.0 → 1.1 (145 scenarios, 13 families), six context
  methods, Opus-judged; GO on both response models. `docs/results/F0_RESULTS.md`,
  `docs/results/F0_PHASE_REPORT.md`.
