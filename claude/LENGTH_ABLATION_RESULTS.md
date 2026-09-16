# Length Ablation — Results (final experiment)

Run date: 2026-09-16; generated at commit 8aa95b8; interpretation table frozen in `length-ablation/manifest.yaml` at commit 8aa95b8 before the first billed call. Spliced sets tagged `length-ablation`. Responders Sonnet 4.6 / Haiku 4.5 / MiniMax M2.5; judge Llama 4 Maverick only; zero Opus. No conversation text was written or changed in this phase.

**Primary result, `full_history(base) − full_history(60)`, paired over 40 targets:** Claude Sonnet 4.6 -0.065 [-0.158, +0.025] → CLOSED (< +2 pp or negative); Claude Haiku 4.5 -0.115 [-0.200, -0.033] → CLOSED (< +2 pp or negative); MiniMax M2.5 -0.027 [-0.102, +0.042] → CLOSED (< +2 pp or negative); pooled -0.069 [-0.131, -0.010] → CLOSED (< +2 pp or negative).

**Validity diagnostic first (handoff §4):** full-history distractor leakage by length, pooled: base 0.108, 30 0.156, 60 0.033. **Leakage does not rise with length: the donor selection failed as the pilot's generation did, and the run is void.** The numbers below are reported for the record only.

## 1. Construction and pre-flight (handoff §2–3)

40 targets (first 8 ids of two_branch_join, three_way_join, resume, long_noisy_side_thread, new_root); donor pool of 164 branches from the other 144 benchmark-1.1 scenarios, ranked by cosine(branch text, target query) with all-mpnet-base-v2 and taken greedily under the hard exclusion (no named entity shared with the target's gold closure; no query entity in the donor), size-aware so lengths land at 30–36 and 60–66 history turns. Pre-flight: oracle-context hash equal across lengths True (40/40); checklist, query and gold closure byte-identical True; 30 ⊂ 60 and base ⊂ 60 subsequence True; insufficient targets none; donor candidacies rejected by the exclusion 771 (independent re-check on the saved files: 0 violations across 2,731 donor turns). Deviation: long_noisy_side_thread's base histories are 33–40 turns, so its 30-turn arm does not exist (base and 60 only; 8 targets). Mean full-history tokens: base 1,826 → 30-turn 3,990 → 60-turn 8,220.

Base-length arms (`full_history@base`, `oracle_dag`) reuse the F0 / F0.5 answers and their Llama verdicts from check 3: the prompts are byte-identical to what this phase would have generated, so nothing was re-billed. Only the spliced lengths were answered here.

## 2. Stage 1 — per-cell diagnostics (checklist, leakage, retraction, tokens)

| model | arm | length | n | checklist | leakage | retraction | context_tokens | context_recall | context_precision |
|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | full_history | 30 | 32 | 0.9167 | 0.1875 | 0.0000 | 3990.1875 | 1.0000 | 0.1279 |
| Claude Sonnet 4.6 | full_history | 60 | 40 | 0.9188 | 0.0500 | 0.0000 | 8220.3250 | 1.0000 | 0.0579 |
| Claude Sonnet 4.6 | full_history | base | 40 | 0.8542 | 0.1250 | 0.0750 | 1825.9750 | 1.0000 | 0.4084 |
| Claude Sonnet 4.6 | oracle_dag | base | 40 | 0.8771 | 0.0250 | 0.0750 | 435.1000 | 1.0000 | 1.0000 |
| Claude Sonnet 4.6 | semantic_retrieval@matched | 30 | 32 | 0.7786 | 0.1562 | 0.0938 | 453.2188 | 0.8187 | 0.8272 |
| Claude Sonnet 4.6 | semantic_retrieval@matched | 60 | 40 | 0.8292 | 0.0000 | 0.0750 | 426.6500 | 0.8341 | 0.8409 |
| Claude Sonnet 4.6 | semantic_retrieval@matched | base | 40 | 0.8500 | 0.0500 | 0.1000 | 431.2250 | 0.9615 | 0.9639 |
| Claude Haiku 4.5 | full_history | 30 | 32 | 0.8385 | 0.1562 | 0.0312 | 3990.1875 | 1.0000 | 0.1279 |
| Claude Haiku 4.5 | full_history | 60 | 40 | 0.9167 | 0.0250 | 0.0000 | 8220.3250 | 1.0000 | 0.0579 |
| Claude Haiku 4.5 | full_history | base | 40 | 0.8021 | 0.0750 | 0.0500 | 1825.9750 | 1.0000 | 0.4084 |
| Claude Haiku 4.5 | oracle_dag | base | 40 | 0.8708 | 0.0250 | 0.1500 | 435.1000 | 1.0000 | 1.0000 |
| Claude Haiku 4.5 | semantic_retrieval@matched | 30 | 32 | 0.7005 | 0.1250 | 0.2188 | 453.2188 | 0.8187 | 0.8272 |
| Claude Haiku 4.5 | semantic_retrieval@matched | 60 | 40 | 0.7833 | 0.0750 | 0.2000 | 426.6500 | 0.8341 | 0.8409 |
| Claude Haiku 4.5 | semantic_retrieval@matched | base | 40 | 0.8688 | 0.0000 | 0.1500 | 431.2250 | 0.9615 | 0.9639 |
| MiniMax M2.5 | full_history | 30 | 32 | 0.9036 | 0.1250 | 0.0000 | 3990.1875 | 1.0000 | 0.1279 |
| MiniMax M2.5 | full_history | 60 | 40 | 0.9125 | 0.0250 | 0.0000 | 8220.3250 | 1.0000 | 0.0579 |
| MiniMax M2.5 | full_history | base | 40 | 0.8854 | 0.1250 | 0.0250 | 1825.9750 | 1.0000 | 0.4084 |
| MiniMax M2.5 | oracle_dag | base | 40 | 0.9292 | 0.0000 | 0.0000 | 435.1000 | 1.0000 | 1.0000 |
| MiniMax M2.5 | semantic_retrieval@matched | 30 | 32 | 0.8359 | 0.0938 | 0.0938 | 453.2188 | 0.8187 | 0.8272 |
| MiniMax M2.5 | semantic_retrieval@matched | 60 | 40 | 0.8854 | 0.0256 | 0.0500 | 426.6500 | 0.8341 | 0.8409 |
| MiniMax M2.5 | semantic_retrieval@matched | base | 40 | 0.9375 | 0.0000 | 0.0000 | 431.2250 | 0.9615 | 0.9639 |

Retraction uses the pilot's heuristic (regex on the answer opening). The oracle arm here is 1.1's; its retraction rate is the confirmation that the pilot's retraction was a property of the pilot's generator, not of pruned context per se.

## 3. Stage 1 — paired contrasts (cluster bootstrap over target ids, 10,000 resamples, pinned per-comparison seeds)

| model | a | b | n | Δ checklist (a − b) | CI low | CI high | SE | tokens a | tokens b |
|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | full_history@base | full_history@60 | 40 | -0.0646 | -0.1583 | 0.0250 | 0.0481 | 1825.9750 | 8220.3250 |
| Claude Sonnet 4.6 | full_history@base | full_history@30 | 32 | -0.0833 | -0.1901 | 0.0156 | 0.0534 | 936.8125 | 3990.1875 |
| Claude Sonnet 4.6 | full_history@30 | full_history@60 | 32 | 0.0026 | -0.0495 | 0.0547 | 0.0274 | 3990.1875 | 8027.1875 |
| Claude Sonnet 4.6 | oracle_dag@base | full_history@base | 40 | 0.0229 | -0.0333 | 0.0854 | 0.0307 | 435.1000 | 1825.9750 |
| Claude Sonnet 4.6 | oracle_dag@base | full_history@30 | 32 | -0.0469 | -0.1380 | 0.0339 | 0.0449 | 461.7188 | 3990.1875 |
| Claude Sonnet 4.6 | oracle_dag@base | full_history@60 | 40 | -0.0417 | -0.1188 | 0.0292 | 0.0387 | 435.1000 | 8220.3250 |
| Claude Haiku 4.5 | full_history@base | full_history@60 | 40 | -0.1146 | -0.2000 | -0.0333 | 0.0426 | 1825.9750 | 8220.3250 |
| Claude Haiku 4.5 | full_history@base | full_history@30 | 32 | -0.0469 | -0.1250 | 0.0234 | 0.0380 | 936.8125 | 3990.1875 |
| Claude Haiku 4.5 | full_history@30 | full_history@60 | 32 | -0.0807 | -0.1719 | 0.0052 | 0.0462 | 3990.1875 | 8027.1875 |
| Claude Haiku 4.5 | oracle_dag@base | full_history@base | 40 | 0.0688 | 0.0062 | 0.1396 | 0.0340 | 435.1000 | 1825.9750 |
| Claude Haiku 4.5 | oracle_dag@base | full_history@30 | 32 | 0.0312 | -0.0703 | 0.1302 | 0.0522 | 461.7188 | 3990.1875 |
| Claude Haiku 4.5 | oracle_dag@base | full_history@60 | 40 | -0.0458 | -0.1042 | 0.0062 | 0.0289 | 435.1000 | 8220.3250 |
| MiniMax M2.5 | full_history@base | full_history@60 | 40 | -0.0271 | -0.1021 | 0.0417 | 0.0365 | 1825.9750 | 8220.3250 |
| MiniMax M2.5 | full_history@base | full_history@30 | 32 | -0.0312 | -0.1198 | 0.0599 | 0.0467 | 936.8125 | 3990.1875 |
| MiniMax M2.5 | full_history@30 | full_history@60 | 32 | -0.0026 | -0.0911 | 0.0755 | 0.0432 | 3990.1875 | 8027.1875 |
| MiniMax M2.5 | oracle_dag@base | full_history@base | 40 | 0.0438 | -0.0271 | 0.1126 | 0.0361 | 435.1000 | 1825.9750 |
| MiniMax M2.5 | oracle_dag@base | full_history@30 | 32 | 0.0312 | -0.0573 | 0.1328 | 0.0485 | 461.7188 | 3990.1875 |
| MiniMax M2.5 | oracle_dag@base | full_history@60 | 40 | 0.0167 | -0.0312 | 0.0667 | 0.0257 | 435.1000 | 8220.3250 |
| pooled | full_history@base | full_history@60 | 40 | -0.0688 | -0.1306 | -0.0097 | 0.0315 | 1825.9750 | 8220.3250 |
| pooled | full_history@base | full_history@30 | 32 | -0.0538 | -0.1137 | 0.0043 | 0.0305 | 936.8125 | 3990.1875 |
| pooled | full_history@30 | full_history@60 | 32 | -0.0269 | -0.0712 | 0.0191 | 0.0231 | 3990.1875 | 8027.1875 |
| pooled | oracle_dag@base | full_history@base | 40 | 0.0451 | -0.0014 | 0.0944 | 0.0247 | 435.1000 | 1825.9750 |
| pooled | oracle_dag@base | full_history@30 | 32 | 0.0052 | -0.0582 | 0.0642 | 0.0316 | 461.7188 | 3990.1875 |
| pooled | oracle_dag@base | full_history@60 | 40 | -0.0236 | -0.0667 | 0.0160 | 0.0218 | 435.1000 | 8220.3250 |

## 4. Interpretation (fixed in advance, applied mechanically)

| observed `full_history(base) − full_history(60)` | reading |
|---|---|
| ≥ +5 pp, CI excludes zero | AMPLIFIES |
| +2 to +5 pp | DIRECTIONAL, under-powered at n=40 |
| < +2 pp, or negative | CLOSED: full history does not degrade to 60 turns on this benchmark; the quality claim is closed, as a finding |

- Claude Sonnet 4.6: -0.0646 [-0.1583, +0.0250] → **CLOSED (< +2 pp or negative)**
- Claude Haiku 4.5: -0.1146 [-0.2000, -0.0333] → **CLOSED (< +2 pp or negative)**
- MiniMax M2.5: -0.0271 [-0.1021, +0.0417] → **CLOSED (< +2 pp or negative)**
- pooled: -0.0688 [-0.1306, -0.0097] → **CLOSED (< +2 pp or negative)**

## 5. Stage 2 — retrieval at matched budget by length

| model | a | b | n | Δ checklist (a − b) | CI low | CI high | tokens a | tokens b |
|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | oracle_dag@base | semantic_retrieval@matched@base | 40 | 0.0271 | -0.0250 | 0.0854 | 435.1000 | 431.2250 |
| Claude Sonnet 4.6 | oracle_dag@base | semantic_retrieval@matched@30 | 32 | 0.0911 | 0.0130 | 0.1797 | 461.7188 | 453.2188 |
| Claude Sonnet 4.6 | oracle_dag@base | semantic_retrieval@matched@60 | 40 | 0.0479 | -0.0271 | 0.1271 | 435.1000 | 426.6500 |
| Claude Sonnet 4.6 | semantic_retrieval@matched@base | semantic_retrieval@matched@60 | 40 | 0.0208 | -0.0417 | 0.0875 | 431.2250 | 426.6500 |
| Claude Haiku 4.5 | oracle_dag@base | semantic_retrieval@matched@base | 40 | 0.0021 | -0.0396 | 0.0479 | 435.1000 | 431.2250 |
| Claude Haiku 4.5 | oracle_dag@base | semantic_retrieval@matched@30 | 32 | 0.1693 | 0.0703 | 0.2760 | 461.7188 | 453.2188 |
| Claude Haiku 4.5 | oracle_dag@base | semantic_retrieval@matched@60 | 40 | 0.0875 | 0.0104 | 0.1729 | 435.1000 | 426.6500 |
| Claude Haiku 4.5 | semantic_retrieval@matched@base | semantic_retrieval@matched@60 | 40 | 0.0854 | 0.0146 | 0.1646 | 431.2250 | 426.6500 |
| MiniMax M2.5 | oracle_dag@base | semantic_retrieval@matched@base | 40 | -0.0083 | -0.0667 | 0.0500 | 435.1000 | 431.2250 |
| MiniMax M2.5 | oracle_dag@base | semantic_retrieval@matched@30 | 32 | 0.0990 | -0.0052 | 0.2031 | 461.7188 | 453.2188 |
| MiniMax M2.5 | oracle_dag@base | semantic_retrieval@matched@60 | 40 | 0.0438 | -0.0354 | 0.1271 | 435.1000 | 426.6500 |
| MiniMax M2.5 | semantic_retrieval@matched@base | semantic_retrieval@matched@60 | 40 | 0.0521 | -0.0167 | 0.1188 | 431.2250 | 426.6500 |
| pooled | oracle_dag@base | semantic_retrieval@matched@base | 40 | 0.0069 | -0.0278 | 0.0424 | 435.1000 | 431.2250 |
| pooled | oracle_dag@base | semantic_retrieval@matched@30 | 32 | 0.1198 | 0.0443 | 0.2005 | 461.7188 | 453.2188 |
| pooled | oracle_dag@base | semantic_retrieval@matched@60 | 40 | 0.0597 | -0.0028 | 0.1271 | 435.1000 | 426.6500 |
| pooled | semantic_retrieval@matched@base | semantic_retrieval@matched@60 | 40 | 0.0528 | -0.0028 | 0.1118 | 431.2250 | 426.6500 |

Retrieval context recall by length (budget = the target's oracle_dag tokens, so what it retrieves changes with the history):

| model | length | n | context_recall | context_precision | checklist | leakage | retraction |
|---|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 30 | 32 | 0.8187 | 0.8272 | 0.7786 | 0.1562 | 0.0938 |
| Claude Sonnet 4.6 | 60 | 40 | 0.8341 | 0.8409 | 0.8292 | 0.0000 | 0.0750 |
| Claude Sonnet 4.6 | base | 40 | 0.9615 | 0.9639 | 0.8500 | 0.0500 | 0.1000 |
| Claude Haiku 4.5 | 30 | 32 | 0.8187 | 0.8272 | 0.7005 | 0.1250 | 0.2188 |
| Claude Haiku 4.5 | 60 | 40 | 0.8341 | 0.8409 | 0.7833 | 0.0750 | 0.2000 |
| Claude Haiku 4.5 | base | 40 | 0.9615 | 0.9639 | 0.8688 | 0.0000 | 0.1500 |
| MiniMax M2.5 | 30 | 32 | 0.8187 | 0.8272 | 0.8359 | 0.0938 | 0.0938 |
| MiniMax M2.5 | 60 | 40 | 0.8341 | 0.8409 | 0.8854 | 0.0256 | 0.0500 |
| MiniMax M2.5 | base | 40 | 0.9615 | 0.9639 | 0.9375 | 0.0000 | 0.0000 |

## 6. Cost

Spend: **$4.78** across 1,112 calls (4,907,607 input / 362,106 output tokens). Estimate $8, warning $10, hard limit $15; Stage-2 gate $7 after Stage 1. Generation cost $0 by construction; base arms reused at $0.

| purpose | usd |
|---|---|
| answer-stage1 | 2.751 |
| answer-stage2 | 1.102 |
| judge | 0.924 |

| model | usd |
|---|---|
| us.anthropic.claude-sonnet-4-6 | 2.429 |
| us.meta.llama4-maverick-17b-instruct-v1:0 | 0.924 |
| us.anthropic.claude-haiku-4-5-20251001-v1:0 | 0.790 |
| minimax.minimax-m2.5 | 0.590 |
| global.anthropic.claude-sonnet-4-6 | 0.033 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | 0.010 |

## 9. Anything else found (future work; not fixed, no follow-up run proposed)

- long_noisy_side_thread has no 30-turn arm (base already 33–40 turns); its rows contribute to base→60 only.
- Donor branches carry their own internal chain links but lose links to their source scenario's gold turns (those are not spliced); the text is unchanged, and `oracle_dag` never sees donor turns, so this affects nothing measured here.
- Base-length arms are reused from F0/F0.5 (temperature-0 samples from earlier days); with 27% decoder variance per cell this is one sample either way, but a fresh base sample would be the cleaner design if this were repeated.
- `BENCHMARK_1.2_PILOT_Analysis_and_Recommendations.md`, listed as required reading, is not in the repository.
