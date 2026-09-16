# ContextDAG — Judge Recalibration Extension: Full Context and Instructions

Prepared 14 September 2026, for execution in a **fresh Claude Code session** with access to the *same* repo checkout F0.5 used (`github.com/chleiva/ContextDAG`, working directory `f05-candidate-realism/` — this extends that directory's existing calibration artifacts in place; it does not create a new phase directory). This document is self-contained — paste it whole into a fresh session. It assumes that session can read `f05-candidate-realism/results/scored/calibration_scores.jsonl` and the calibration harness that produced it; if paths differ from what's written below, locate the equivalent files rather than treating the exact paths as load-bearing.

This is **not** a re-run of F0.5. It is a small, cheap extension of one step inside it (§1.3 of `F0.5_CANDIDATE_REALISM_HANDOFF.md`), done to fix a bar that was measuring the wrong thing and to widen the candidate pool before committing to a standing judge for every phase after this one.

---

## 0. Why this exists, and the two things it changes

F0.5's judge calibration scored four cross-vendor candidates (DeepSeek V3.2, Kimi K2.5, Llama 4 Maverick, Mistral Large 3) against Claude Opus 4.6 on an 80→160-instance sample, and rejected all four on `mean |Δ| ≤ 0.05` — a per-instance absolute-score-difference bar. That rejection was correct *given that bar*, and the bar was not moved after seeing results, which was the right call at the time. But the bar itself measured the wrong quantity: `mean |Δ|` is dominated by symmetric per-item disagreement that averages out over any mean-of-145-scenarios or paired-bootstrap comparison — which is every comparison this project actually reports. The quantity that can corrupt a result is bias that differs *by method*, not raw per-instance noise. Full derivation: `docs/reviews/F0.5_Analysis_and_Recommendations.md` §6.

Two changes, both decided 14 September 2026, both implemented here:

1. **Replace the adoption bar** with one that measures method-contrast error instead of per-instance error (§2 below).
2. **Add three new candidate judges** to the pool, re-scored on the *same* 160 instances so no new Opus calls are needed: `gpt-oss-120b` on Bedrock, and **GPT-5 Mini** / **GPT-5 Nano** via the OpenAI API directly (a separate credential from Bedrock — see §3).

**Standing policy from here forward: no new Opus 4.6 calls except where explicitly listed as required below.** Opus's existing verdicts on the 160-instance calibration set (and F0's ~2,600 verdicts more broadly) are sunk cost and stay in use as the reference — re-scoring new candidates against them is free beyond the new candidate's own inference. This extension is designed to spend a few tens of cents total and end Opus's role as the working judge for every phase after this one.

---

## 1. What's reused (zero new cost) vs. new

**Reused, zero cost:**
- The 160-instance calibration subsample itself (family-proportional across all 13 families, split evenly between Sonnet 4.6 / Haiku 4.5, spread across full_history / sliding_window@1024 / semantic_retrieval@1024 / oracle_tree / oracle_dag). Same instances — do not resample.
- Opus 4.6's reference verdicts on those 160 instances, already recorded in `results/scored/calibration_scores.jsonl` (or wherever the F0.5 harness wrote them — confirm the path, don't recreate the sample).
- DeepSeek V3.2, Kimi K2.5, Llama 4 Maverick, and Mistral Large 3's existing scores on the same 160 instances (already paid for; only their *evaluation against the new bar* is new work, not their inference).

**New (§3, §4):**
- `gpt-oss-120b` scored on the same 160 instances via Bedrock.
- GPT-5 Mini scored on the same 160 instances via the OpenAI API.
- GPT-5 Nano scored on the same 160 instances via the OpenAI API (include this one purely because the marginal cost is near-zero once the OpenAI integration exists for GPT-5 Mini — it is not expected to win, small models tend to lose rubric-grading reliability, but checking costs pennies).

---

## 2. Corrected adoption bar — freeze this before scoring anything, per this project's pre-registration discipline

```yaml
judge_adoption_bar_v2:
  item_kappa_min: 0.6                     # unchanged from the original bar
  ranking_preserved: true                 # unchanged; tie band 0.03
  contrast_error_max: 0.02                # NEW — replaces mean_abs_score_delta <= 0.05
  contrasts:                              # the only contrasts this study actually reports
    - dag_minus_full
    - dag_minus_tree
    - dag_minus_sliding
    - dag_minus_semantic
```

For each candidate, compute the same four contrasts on the calibration subsample's method-mean table that Opus's own reference already gives:

| contrast | Opus 4.6 (reference) |
|---|---|
| dag − full | −0.084 |
| dag − tree | +0.042 |
| dag − sliding | +0.153 |
| dag − semantic | −0.090 |

A candidate **passes** if: item κ ≥ 0.6, method ranking matches Opus's (tie band 0.03), and `|candidate's contrast − Opus's contrast|` ≤ 0.02 on **every one** of the four contrasts (not on average — a candidate that's great on three and off by 0.06 on the fourth fails, since that fourth contrast is exactly the kind of comparison this study depends on being right). Report the actual per-contrast errors for every candidate regardless of pass/fail, the same way F0.5 reported calibration data even for the bar it used.

If more than one candidate passes, **prefer the cheapest per-call cost** — do not pay more for a tie, same principle as the original bar's judge-selection rule.

**Do not adjust this bar after seeing results.** If nothing passes, the fallback order is: widen the error tolerance only with the parent conversation's explicit sign-off (this would be a genuine bar change, not a bug fix, and needs the same scrutiny as any other pre-registered threshold change) — do not fall back to Opus by default just because it's familiar.

**Deferred, not part of this extension:** an Opus 4.6 self-test-retest floor (~$3, 40 instances) was proposed in `docs/reviews/F0.5_Analysis_and_Recommendations.md` §6 as a way to check whether Opus agrees with itself as well as candidates are being asked to agree with it. It is *not* required to apply the bar above and is being skipped for now under the "no new Opus spend" policy. Flag it as available future work in the results doc; do not run it without checking in first.

---

## 3. New candidates — specs to verify, not assume

Per this project's own repeated lesson (F0's Bedrock-Mantle 404s, Grok 4.6's account-specific `AccessDenied`, MiniMax M2.5's unconfirmed Bedrock rate): **verify model IDs, reachability, and live pricing before running anything, and record what you found — do not carry the numbers below forward uncritically.**

- **`gpt-oss-120b` on Bedrock.** Likely invocable as `openai.gpt-oss-120b-1:0` via `bedrock-runtime`/`converse` (the same path already proven to work on this account for the other Bedrock judge candidates) — confirm the exact model ID and region against the account, the same way F0's step 1 did for its model tiers. Cost seen in this research pass: **$0.15 / $0.60 per 1M input/output tokens** — reconfirm against the live AWS Bedrock pricing page or the account's actual billed rate before costing anything out.
- **GPT-5 Mini, via the OpenAI API directly (not Bedrock).** Needs a separate credential — the user has a standalone OpenAI API key for this; do not attempt to reach it through Bedrock. Cost seen in this research pass: **$0.25 / $2.00 per 1M**. Confirm current pricing and exact model name at `platform.openai.com/docs/pricing` at run time — OpenAI's naming has moved fast this year (this research pass also surfaced references to GPT-5.4/5.6 variants with different pricing; use whichever current small "mini" tier model the live pricing page shows, and record the exact model string used).
- **GPT-5 Nano, same route as GPT-5 Mini.** Cost seen in this research pass: **$0.05 / $0.40 per 1M**. Same reconfirmation caveat.

**Integration note:** the OpenAI models need a chat-completions-shaped call, not Bedrock's `converse` shape, and their own row in the cost ledger (`cost.py` currently assumes one Bedrock-shaped billing path per F0.5's implementation) — this is the one piece of actual engineering in this extension, everything else is reusing existing harness code with a new model target. Keep the exact same judge prompt/rubric F0.5 used for every other candidate; only the model-invocation layer changes.

**STOP AND CHECK IN** after this step with: confirmed model IDs/routes, confirmed live pricing, and confirmation the OpenAI credential works — before scoring all 160 instances, the same discipline every prior phase in this project has used before committing to a full run.

---

## 4. Step-by-step execution plan

1. **Verify access and pricing** (§3). Stop and check in with findings.
2. **Locate and validate the existing calibration artifacts** — the 160 instances, Opus's reference scores, and the four already-scored cross-vendor candidates. Confirm instance IDs are stable and nothing needs regenerating.
3. **Score all 160 instances with the three new candidates** (gpt-oss-120b, GPT-5 Mini, GPT-5 Nano), reusing F0.5's exact judge prompt. Record every route/model-string used, the same way F0.5's post-mortem on its region/profile fallback did — this project has been burned once already by not tracking that.
4. **Re-derive the four contrasts** (§2) for all seven non-Opus candidates (the four from F0.5 plus these three) from their existing or newly-collected method-mean tables. No new inference needed for the four already-scored candidates — this step is pure re-analysis of numbers already in hand.
5. **Apply the corrected bar mechanically** (§2). Report every candidate's kappa, ranking check, and all four contrast errors in a results table — pass or fail, same as F0.5's own calibration table did.
6. **Select the standing judge**: cheapest candidate that passes, ties broken by cost. If none pass, stop and report that rather than defaulting back to Opus.
7. **Do not proceed to benchmark 1.2 or check 3 from this handoff.** Those are scoped separately. This extension's job ends at "here is the standing judge for future phases, and here is the evidence for why."

---

## 5. Cost guardrail

Expected total spend: **under $1** (three new candidates × 160 instances at the per-call costs in §3, plus negligible retries). Set a nominal hard limit of **$5** anyway, consistent with this project's ledger-enforced-limit habit, even though it should not be approached. If actual spend is tracking meaningfully above $5, stop and report rather than continuing — something unexpected is happening (e.g., a pricing tier or context-length assumption was wrong).

---

## 6. Report template

Write results to `docs/results/JUDGE_RECALIBRATION_RESULTS.md` (project doc, same location as the phase results docs) with:

```markdown
# Judge Recalibration Extension — Results

Run date: ...
Instances: 160 (reused from F0.5, no resampling)
New candidates scored: gpt-oss-120b (route: ...), GPT-5 Mini (model string: ...), GPT-5 Nano (model string: ...)
Bar applied: judge_adoption_bar_v2 (§2 of this handoff)

## Per-candidate results
(table: candidate | item_kappa | ranking_preserved | dag-full err | dag-tree err | dag-sliding err | dag-semantic err | pass/fail | $/call)

## Decision
Standing judge selected: ...
Why (cheapest passer, or — if none passed — what happened and what's next)

## Cost
(actual spend vs. the <$1 estimate)

## What this unblocks
Confirms the judge to use for benchmark 1.2 and check 3, both still separately scoped.
```

Update `docs/results/SESSION_STATE_AND_NEXT_STEPS.md`'s judge-policy section with the outcome once this completes — that document is what the next session (or the one planning benchmark 1.2) will read first.