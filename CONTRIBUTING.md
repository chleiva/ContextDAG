# Contributing

Thanks for your interest. This is a research repository: the value is in the benchmark, the
pre-registered evaluation procedure, and the traceability from every number in a report back to a
manifest, a ledger entry, and a raw model call. Contributions should preserve that.

## Ground rules

- **Never modify a committed scenario, checklist, or gold closure** of a benchmark version that a
  completed phase depends on. Add a new benchmark version instead (see how `benchmark12-pilot/`
  and `length-ablation/` add scenarios without touching `f0-oracle-feasibility/data/`).
- **Freeze thresholds before spending.** Every phase commits its decision thresholds in
  `manifest.yaml` before the first billed call, and the results document quotes them. Do not adjust
  a threshold after seeing results; if a threshold turns out to be unreachable or mis-specified,
  record that in the results document (see `docs/results/CHECK3_REWORK_RESULTS.md` for the pattern).
- **Every LLM call goes through the ledger.** Use the phase's `complete()` wrapper
  (`f05-candidate-realism/src/f05_llm.py`), which records tokens and price and refuses to start past
  the hard limit. Add a price entry to the manifest before calling a new model id, including the
  `global.` / `us.` inference-profile spellings.
- **No secrets in the repo.** Credentials live only in the git-ignored `.env`; see `SECURITY.md`.
- **Report what happened.** Failures, wasted spend, and deviations from a handoff belong in the
  results document, in a numbered "anything else found" section, not in a commit message alone.

## Development setup

```
uv venv .venv --python 3.11 && . .venv/bin/activate
uv pip install -r requirements.lock
python -m spacy download en_core_web_sm      # only for candidate generation / splicing
cp .env.example .env                          # fill in credentials only if you will make model calls
make test                                     # no network, no model calls
```

## Adding a phase

1. Create a sibling directory with its own `manifest.yaml` (models, prices, thresholds, budget),
   `src/`, `data/` (if it adds scenarios), and `results/`.
2. Point the shared client and ledger at it with `F05_ROOT=<dir>` (see `benchmark12-pilot/src/pilot.py`).
3. Make every stage resumable and keyed (`scenario|method|budget|model`), so a crash or a quota stall
   never repeats billed work.
4. Write the results document from the committed tables with a script, so regenerating it from the
   same inputs is byte-identical; use pinned per-comparison bootstrap seeds.
5. Commit the frozen manifest before the first billed call.

## Pull requests

Keep them scoped to one phase or one fix. Include the ledger delta if the change made model calls,
and the regenerated results document if it changes any reported number. `make test` must pass.
