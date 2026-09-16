# ContextDAG

[![ci](https://github.com/chleiva/ContextDAG/actions/workflows/ci.yml/badge.svg)](https://github.com/chleiva/ContextDAG/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Data: CC-BY-4.0](https://img.shields.io/badge/data-CC--BY--4.0-green.svg)](f0-oracle-feasibility/data/LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](pyproject.toml)

Research framework for **dependency-graph context management** in multi-turn LLM conversations: build a model's context from the branches a new message actually depends on, including joins of previously separate branches, instead of the chronological transcript. This repository holds the synthetic benchmark, six context-construction methods, a staged and pre-registered evaluation with every threshold frozen before spend, every LLM call's cost ledger, and the results.

> **Status (16 September 2026): experiments complete; the next deliverable is the paper.** The project is an oracle-first evaluation, not a usable library. There is no automatic router yet; every "DAG" result below uses the hand-labelled gold dependency graph, and the candidate-realism phase bounds what a cheap real system could reach.

## What was found

| Phase | Question | Verdict | Where |
|---|---|---|---|
| **F0** oracle feasibility | Given a perfect dependency graph, does DAG context beat full history, sliding window, rolling summary, semantic retrieval, and a single-parent tree on quality vs tokens? | **GO.** 69% fewer tokens than full history at equal-or-better checklist quality (+2.7 pp Sonnet 4.6, +2.6 pp Haiku 4.5), and +0.32 over the tree on join families. 145 scenarios, 13 families. | [F0_RESULTS](docs/results/F0_RESULTS.md) |
| **F0.5** candidate realism | Can a cheap, non-LLM candidate generator find the gold parent set, and does an oracle restricted to that pool keep the result? | **PASS.** Strict Recall@15 = 0.993; the restricted oracle keeps F0's numbers. Caveat: 1.1's histories are short, so k=15 rarely binds; Recall@5 = 0.34. | [F0.5_RESULTS](docs/results/F0.5_RESULTS.md) |
| **Judge recalibration** | Can a cheap cross-vendor judge replace Opus 4.6 without changing conclusions? | **Llama 4 Maverick adopted** on a method-contrast bar (κ 0.77, every contrast within 0.02 of Opus on 1,450 instances) at ~1/25th the cost. | [JUDGE_RECALIBRATION_RESULTS](docs/results/JUDGE_RECALIBRATION_RESULTS.md) |
| **Check 3** retrieval/compression comparability | Does the candidate-realistic oracle keep a distinct advantage over semantic retrieval and rolling summary? | **PASS (non-inferiority + token ratio)** on both models at 0.38–0.53× the baselines' tokens; precision 0.95 vs 0.43–0.49, leakage 1–4% vs 15–19%. Not a powered superiority claim. | [CHECK3_RESULTS](docs/results/CHECK3_RESULTS.md), [rework](docs/results/CHECK3_REWORK_RESULTS.md) |
| **Benchmark 1.2 pilot** | Does a longer history (30–60 turns) amplify the effect? | **FLAT, and negative.** Mechanism: *retraction*. With a pruned context, Sonnet 4.6 (51%) and Haiku 4.5 (28%) disown assistant-stated facts as fabrications. Efficiency holds (0.13× tokens). | [BENCHMARK_1.2_PILOT_RESULTS](docs/results/BENCHMARK_1.2_PILOT_RESULTS.md) |
| **Length ablation** (final) | Same question, with validated distractors spliced in and nothing else changed. | **Void under its own validity rule**: leakage fell with length, full history got easier. Two instruments failed to make distractors harder with length. | [LENGTH_ABLATION_RESULTS](docs/results/LENGTH_ABLATION_RESULTS.md) |

The claims this supports, in order of strength, and the limitations to state, are listed in the final handoff's §10: [docs/handoffs/LENGTH_ABLATION_HANDOFF.md](docs/handoffs/LENGTH_ABLATION_HANDOFF.md). Total model spend across the project: **$124** ([docs/COSTS.md](docs/COSTS.md)).

## How the evaluation was run

- **Structure first.** A seeded builder decides each scenario's dependency graph, gold closure, and distractor structure in code; an LLM only writes the dialogue and the checklist. Every scenario is validated (structure, closure, banned topic-switch signposting) before admission.
- **Six context methods** on identical prompts: `full_history`, `sliding_window@{1024,2048}`, `rolling_summary@{1024,2048}`, `semantic_retrieval@{512,1024,2048,matched}` (all-mpnet-base-v2, turn-level), `oracle_tree` (primary parents only), `oracle_dag` (full ancestor closure), plus the candidate-restricted `candidate_oracle@k`.
- **Judging** by checklist (TRUE/FALSE per required item, plus a distractor-leakage flag) with a fixed rubric; Opus 4.6 for F0/F0.5, Llama 4 Maverick after calibration.
- **Statistics:** paired differences per scenario, cluster bootstrap over scenario ids with 10,000 resamples and pinned per-comparison seeds, Holm adjustment on confirmatory sets, per-family intervals read against a measured noise floor (temperature-0 decoding on Bedrock is not deterministic: 27% of per-scenario variance).
- **Pre-registration discipline:** thresholds are committed in each phase's `manifest.yaml` before the first billed call and applied mechanically; deviations, unreachable branches, and mistakes are recorded in the results documents rather than corrected silently.
- **Cost control:** every call goes through a ledger that prices actual token usage, warns past an estimate, and refuses to start past a hard limit. Region and inference-profile fallback is built into the client; the route is recorded per call.

## Layout

```
f0-oracle-feasibility/   benchmark 1.1 (145 scenarios, CC-BY-4.0), six methods, F0 run: manifest, src, data, results
f05-candidate-realism/   candidate generator, Recall@k, judge calibration, check 3 (+ rework), shared multi-backend client
benchmark12-pilot/       long-scenario generator with generation-time assertions, 39 long scenarios (tag 1.2-pilot)
length-ablation/         splice construction with pre-flight, 72 spliced sets (tag length-ablation)
docs/results/            one results document per phase          docs/handoffs/   the instructions each phase ran from
docs/reviews/            independent critical review              docs/SESSION_STATE.md, docs/COSTS.md
tests/                   offline integrity tests (schema, splice invariants, analysis guards, ledgers)
```

Each phase directory has a `manifest.yaml` (models, prices, thresholds, budget), `src/`, and `results/` with raw answers, judge verdicts, tables, figures, and the cost ledger. See [docs/README.md](docs/README.md) for the reading order.

## Reproduce

Everything reported can be re-derived from the committed raw answers and verdicts without any model call:

```
make setup              # Python 3.11 + uv; installs requirements.lock and the spaCy model
make test               # offline integrity tests
make analyze-f0 analyze-f05 analyze-check3 analyze-pilot analyze-ablation
make reports            # regenerates docs/results/*.md from the tables
```

Re-running the model calls needs Amazon Bedrock credentials in `.env` (see `.env.example`) and, for the recalibration's OpenAI candidates, an OpenAI key. Every stage is resumable and keyed by `scenario|method|budget|model`, so an interrupted run never repeats billed work. Budgets in each manifest cap spend.

## Licensing

- **Code**: Apache-2.0 (`LICENSE`, `NOTICE`).
- **Benchmark data created here** (`*/data/scenarios/`): [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). All text is synthetic; people, organisations, and figures are invented.
- **External datasets** are never redistributed; `DATA_SOURCES.md` records what was considered and its terms.

## Citing

See [CITATION.cff](CITATION.cff). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Security and credentials: [SECURITY.md](SECURITY.md).
