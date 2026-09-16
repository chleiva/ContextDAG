# Costs

Every LLM call in this project was recorded by a ledger before analysis (actual token usage × Bedrock/OpenAI list price). Per-phase totals from the committed ledgers:

| Phase | Calls | Input tokens | Output tokens | USD |
|---|---|---|---|---|
| F0 oracle feasibility (incl. benchmark 1.1 fixes) | 6,308 | 9,618,883 | 1,997,469 | 72.86 |
| F0.5 candidate realism | 2,124 | 3,249,279 | 702,365 | 15.78 |
| Judge recalibration | 2,096 | 3,682,257 | 1,000,381 | 1.97 |
| Check 3 (incl. rework) | 4,172 | 6,481,743 | 1,268,470 | 5.20 |
| Benchmark 1.2 Stage A pilot | 1,093 | 4,988,710 | 1,495,292 | 23.55 |
| Length ablation | 1,112 | 4,907,607 | 362,106 | 4.78 |
| **Total** | **16,905** | **32,928,479** | **6,826,083** | **124.14** |

Notes:
- The Opus 4.6 judge accounts for roughly $64 of the total (F0 and F0.5). After the judge recalibration, Llama 4 Maverick judged every later phase at about 1/25th of that cost; no Opus calls were made after the check-3 rework's 32 audited re-judgements.
- Two disclosed leaks: 113 answer calls in the check-3 rework were billed by AWS but rejected by the ledger before a profile-pricing fix (≈ $0.50); the benchmark 1.2 pilot wasted $4.96 on generator defects fixed mid-run.
- Ledger files: `*/results/raw/cost_ledger*.jsonl`. Budgets and price tables are in each phase's `manifest.yaml`.
