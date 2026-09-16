# Documentation index

Read in this order if you are new to the project.

## Results (one document per phase; each quotes its frozen thresholds and applies them mechanically)

| Phase | Document | Verdict |
|---|---|---|
| F0 oracle feasibility | [F0_RESULTS.md](results/F0_RESULTS.md), narrative [F0_PHASE_REPORT.md](results/F0_PHASE_REPORT.md) | GO on both response models |
| F0.5 candidate realism | [F0.5_RESULTS.md](results/F0.5_RESULTS.md) | PASS on both |
| Judge recalibration | [JUDGE_RECALIBRATION_RESULTS.md](results/JUDGE_RECALIBRATION_RESULTS.md) | Llama 4 Maverick adopted as standing judge |
| Check 3 retrieval/compression comparability | [CHECK3_RESULTS.md](results/CHECK3_RESULTS.md), rework [CHECK3_REWORK_RESULTS.md](results/CHECK3_REWORK_RESULTS.md) | PASS (non-inferiority + token ratio) |
| Benchmark 1.2 Stage A length pilot | [BENCHMARK_1.2_PILOT_RESULTS.md](results/BENCHMARK_1.2_PILOT_RESULTS.md) | FLAT; retraction failure mode found |
| Length ablation (final experiment) | [LENGTH_ABLATION_RESULTS.md](results/LENGTH_ABLATION_RESULTS.md) | Void under its validity rule; negative observation |

## Handoffs and plans (the instructions each phase was run from, verbatim)

- [F0_ORACLE_FEASIBILITY_HANDOFF.md](handoffs/F0_ORACLE_FEASIBILITY_HANDOFF.md)
- [F0.5_CANDIDATE_REALISM_HANDOFF.md](handoffs/F0.5_CANDIDATE_REALISM_HANDOFF.md) and the executing plan [F0.5_PLAN.md](handoffs/F0.5_PLAN.md)
- [JUDGE_RECALIBRATION_HANDOFF.md](handoffs/JUDGE_RECALIBRATION_HANDOFF.md)
- [CHECK3_HANDOFF.md](handoffs/CHECK3_HANDOFF.md), plan [CHECK3_PLAN.md](handoffs/CHECK3_PLAN.md), rework [CHECK3_REWORK_HANDOFF.md](handoffs/CHECK3_REWORK_HANDOFF.md)
- [BENCHMARK_1.2_STAGE_A_HANDOFF.md](handoffs/BENCHMARK_1.2_STAGE_A_HANDOFF.md), plan [BENCHMARK_1.2_PILOT_PLAN.md](handoffs/BENCHMARK_1.2_PILOT_PLAN.md)
- [LENGTH_ABLATION_HANDOFF.md](handoffs/LENGTH_ABLATION_HANDOFF.md)

## Reviews

- [F0.5_Analysis_and_Recommendations.md](reviews/F0.5_Analysis_and_Recommendations.md), the independent critical review that shaped check 3 and the judge recalibration.

## Project state and bookkeeping

- [SESSION_STATE.md](SESSION_STATE.md): where the project stands, decisions carried forward, what comes next (the paper).
- [COSTS.md](COSTS.md): per-phase spend from the committed ledgers.
- [../DATA_SOURCES.md](../DATA_SOURCES.md): external datasets considered and their terms (none redistributed).
