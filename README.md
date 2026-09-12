# ContextDAG

Research framework for dependency-graph context management in multi-turn LLM conversations — routes context by what a message actually depends on, not chronology, with an oracle-first benchmark testing whether that helps versus full-history, retrieval, and compression baselines.

> **Early-stage research.** This repository currently contains only the **F0 oracle feasibility study**, the first step in a staged evaluation plan before any automatic system is built. It is not a usable framework yet. Anyone cloning early should expect a benchmark and an offline experiment, not a library.

## What F0 asks

ContextDAG's hypothesis is that representing a conversation as a dependency graph (rather than a flat transcript) lets you build model context from only the branches a new message depends on, including joins of two or more previously separate branches, while using far fewer tokens than the full history and without losing answer quality.

F0 tests the *ceiling* of that idea before anything automatic is built: **given a perfect, hand-labeled dependency graph, does the resulting context beat strong baselines on the quality-versus-tokens trade-off?** Six context construction methods (full history, sliding window, rolling summary, semantic retrieval, oracle single-parent tree, oracle multi-parent DAG) are run over a synthetic benchmark of ~140 annotated conversations across 13 structural families. Pre-registered thresholds in `f0-oracle-feasibility/manifest.yaml` turn the result into a mechanical GO / PIVOT / STOP.

Related prior work exists on both sides of this idea: multi-parent DAGs for agent trajectories, and tree- or graph-structured conversation UIs for human chat. ContextDAG does not claim graph-structured context is novel in itself; the question is whether dependency-structured context *measurably helps* on the trade-off above.

## Layout

```
f0-oracle-feasibility/
  manifest.yaml          # models, thresholds, budgets: the one file the run is reproducible from
  data/scenarios/*.json  # the synthetic benchmark (CC-BY-4.0)
  src/                   # schema, generation, context methods, metrics, experiment, scoring, analysis
  results/               # raw call logs, judge scores, tables, plots
  F0_RESULTS.md          # the report (written after the run)
```

## Setup

Python 3.11+. Models are served through Amazon Bedrock.

```
uv venv .venv --python 3.11 && . .venv/bin/activate
uv pip install "anthropic[bedrock]" sentence-transformers tiktoken numpy pandas matplotlib pyyaml pydantic
cp .env.example .env   # then fill in AWS_BEARER_TOKEN_BEDROCK
```

## Licensing

Three kinds of material, three licenses:

- **Code** — Apache-2.0 (`LICENSE`, `NOTICE`).
- **Benchmark data created by this project** (the synthetic scenarios under `f0-oracle-feasibility/data/`, and eventually the full ContextDAG-Bench) — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). See `f0-oracle-feasibility/data/LICENSE`.
- **External benchmark data** (NTM, TopiOCQA, LoCoMo, LongMemEval, or anything else sourced later) — never redistributed here. Download and adapter scripts only; each source's own license and terms are recorded in `DATA_SOURCES.md`.
