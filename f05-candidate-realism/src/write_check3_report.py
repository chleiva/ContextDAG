"""Fill claude/CHECK3_RESULTS.md from results/check3/* (check3-handoof.md §4, §7)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("F05_LEDGER", "check3")
from f0_bridge import REPO, ROOT, load_manifest  # noqa: E402
from f05_cost import ledger  # noqa: E402

C3 = ROOT / "results" / "check3"
OUT = REPO / "claude" / "CHECK3_RESULTS.md"
DISCLOSURE = """This analysis is **confirmatory-with-disclosure, not blind pre-registration**, and must be described that way in any writeup.

One point estimate is already known. Deriving it from the enlarged-sample contrasts in `JUDGE_RECALIBRATION_RESULTS.md`, pooled over Sonnet and Haiku on benchmark 1.1:

| method | checklist | context tokens |
|---|---|---|
| full_history | 0.838 | 1,508 |
| semantic_retrieval@1024 | 0.841 (derived) | ~900–1,080 |
| oracle_dag | 0.865 | 471 |
| candidate_oracle@15 | 0.869 | 472 |

so `candidate_oracle@15 − semantic_retrieval@1024 ≈ +0.028` pooled. That number was computed before this handoff was written and cannot be un-seen.

**What remains genuinely blind, and is the substance of this pass:** all confidence intervals; the per-family breakdown; `@2048` configurations; both `rolling_summary` budgets; the second-judge replication; the MiniMax arm; and the token-side comparison. Freeze §1's thresholds before computing any of those. Do not adjust them afterwards. Record in the results doc which quantities were known in advance (the one above) and which were not."""


def md(df: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "" if pd.isna(x) else fmt.format(x))
    cols = [str(c) for c in df.columns]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
                     + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |" for _, r in df.iterrows()])


def main() -> None:
    man = load_manifest(); c3 = man["check3"]
    disp = {k: man["models"][k]["display"] for k in ("response_a", "response_b", "response_c")}
    comp = pd.read_csv(C3 / "comparisons.csv"); fam = pd.read_csv(C3 / "per_family.csv"); fro = pd.read_csv(C3 / "frontier.csv")
    dec = json.loads((C3 / "decision.json").read_text())
    verb = json.loads((C3 / "verbosity.json").read_text()) if (C3 / "verbosity.json").exists() else None
    L = ledger()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    ref, bases = c3["reference_method"], c3["confirmatory_baselines"]
    A = []
    P = A.append
    P("# Check 3 — Retrieval/Compression Comparability: Results\n")
    P("> **Revised 15 September 2026 (check-3 rework, `claude/CHECK3_REWORK_RESULTS.md`).** Changed in place: (1) the Opus pooled rows in §3 now average only the models that carry verdicts for both arms (Sonnet + Haiku); the previous rows let MiniMax into the reference mean but not the baselines', inflating each Opus pooled Δ by +0.0132. (2) The PASS label in the headline and §4 was renamed to state what the criterion actually tested (non-inferiority + token ratio), and §10 records that the criterion's FAIL branch was unreachable in this design. (3) The judge-agreement paragraph in §3 was rewritten. No per-model numeric table changed; the frontier table gained the `semantic_retrieval@512` sensitivity arm (Llama-judged, exploratory).\n")
    P(f"Run date: {date.today().isoformat()}  ")
    P(f"Frozen thresholds: `f05-candidate-realism/manifest.yaml` → `check3`, committed at d4204fb before any computation; this doc generated at {commit}  ")
    P("Benchmark 1.1, 145 scenarios. Primary judge: Claude Opus 4.6 verdicts already on disk (F0 + F0.5; zero new Opus calls). Replication judge: Llama 4 Maverick. Primary response models: Sonnet 4.6, Haiku 4.5; MiniMax M2.5 secondary.\n")
    verdicts = {mk: dec["primary"][mk]["verdict"] for mk in c3["primary_models"]}
    lab = lambda v: v.replace("PASS (structured context retains a distinct advantage)", "PASS (non-inferiority + token ratio)")  # noqa: E731
    P("**Decision (primary judge, frozen criterion): " + "; ".join(f"{disp[mk]}: {lab(v)}" for mk, v in verdicts.items()) + ".** Replication judge: " + "; ".join(f"{disp[mk]}: {lab(dec['replication_llama'][mk]['verdict'])}" for mk in c3["primary_models"]) + ".\n")
    P("**PASS (non-inferiority + token ratio).** `candidate_oracle@15` is non-inferior at a −0.03 margin to the best retrieval and summarisation configurations while using 38–53% of their context tokens, with context precision 0.95 vs 0.43–0.49 and distractor leakage 1–4% vs 15–19%.\n")
    P("## 0. Integrity disclosure (verbatim from the handoff)\n"); P(DISCLOSURE + "\n")
    P("Known in advance: the pooled `candidate_oracle@15 − semantic_retrieval@1024` point estimate (+0.028). Not known in advance and computed only after the thresholds were committed: every confidence interval, every p-value, the @2048 and rolling_summary comparisons, per-family results, the Llama replication, the MiniMax arm, and the token comparisons.\n")
    P("## 1. Frozen criterion\n")
    P(f"- Reference: `{ref}`; confirmatory baselines: {', '.join(f'`{b}`' for b in bases)}; per response model, Opus judge.")
    P(f"- Non-inferiority margin {c3['non_inferiority_margin']} on the lower bound of the 95% cluster-bootstrap CI ({c3['bootstrap_resamples']:,} resamples over scenario ids) of the paired checklist difference.")
    P(f"- **FAIL** (retrieval/compression comparable) if the best-scoring baseline is non-inferior to the reference and uses ≤ {c3['token_ratio_fail_max']}× its context tokens. **PASS** if the reference is non-inferior to every baseline and uses ≤ {c3['token_ratio_pass_max']}× the tokens of the best-scoring baseline. Otherwise **INDETERMINATE**.")
    P("- Holm adjustment over the four confirmatory comparisons per model (one-sided non-inferiority p = share of bootstrap differences at or below the margin); unadjusted CIs also shown. Per-family intervals read against the 0.075 noise floor.\n")
    P("## 2. Verification checks (handoff §3.1)\n")
    P("- **Turn-order diff.** For all 432 (scenario, model) pairs where `candidate_oracle@15` and `oracle_dag` select the same turn set, the serialised prompts are byte-identical (Sonnet, Haiku, MiniMax alike). No order effect. Only 23 of those 432 identical prompts produced byte-identical answers: temperature 0 on Bedrock is not deterministic, which is the mechanism behind the per-family noise floor.")
    P("- **Off-route judge calls.** All 32 off-route Opus calls in F0.5 (of 731) sit in the MiniMax arm: 9 `candidate_oracle@15`, 10 `full_history`, 13 `oracle_dag`, across `us.`@us-east-1, `us.`@us-west-2 and `global.`@us-west-2. None touch Sonnet or Haiku; the confirmatory set is unaffected. The MiniMax (secondary) arm carries this note.\n")
    P("## 3. Confirmatory comparisons (Opus 4.6; paired difference = reference − baseline)\n")
    cf = comp[comp.confirmatory].copy(); cf["model"] = cf.model.map(disp)
    P(md(cf[["model", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "p_noninferior", "p_holm", "noninferior_ci", "noninferior_holm", "tok_diff", "tok_ratio", "tok_ratio_ci_low", "tok_ratio_ci_high"]].rename(columns={"b": "baseline", "q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "p_noninferior": "p (NI)", "p_holm": "p Holm", "noninferior_ci": "NI (CI)", "noninferior_holm": "NI (Holm)", "tok_diff": "Δ tokens", "tok_ratio": "tokens ref/base", "tok_ratio_ci_low": "ratio CI low", "tok_ratio_ci_high": "ratio CI high"}), "{:.4f}"))
    P("\nReverse direction (is the best baseline non-inferior to the reference? the FAIL arm of the criterion):\n")
    rv = comp[(comp.direction == "baseline_vs_reference") & (comp.judge == "opus") & comp.model.isin(c3["primary_models"])].copy(); rv["model"] = rv.model.map(disp)
    P(md(rv[["model", "a", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio"]].rename(columns={"a": "baseline", "q_diff": "Δ (base − ref)", "q_ci_low": "CI low", "q_ci_high": "CI high", "noninferior_ci": "baseline NI to ref", "tok_ratio": "tokens base/ref"}), "{:.4f}"))
    P("\n### Replication under Llama 4 Maverick (same instances, same comparisons)\n")
    ll = comp[(comp.judge == "llama") & (comp.a == ref) & comp.b.isin(bases) & (comp.direction == "reference_vs_baseline") & comp.model.isin(c3["primary_models"])].copy(); ll["model"] = ll.model.map(disp)
    P(md(ll[["model", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "p_noninferior", "p_holm", "noninferior_ci", "noninferior_holm", "tok_ratio"]].rename(columns={"b": "baseline", "q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "p_noninferior": "p (NI)", "p_holm": "p Holm", "noninferior_ci": "NI (CI)", "noninferior_holm": "NI (Holm)", "tok_ratio": "tokens ref/base"}), "{:.4f}"))
    _ll_raw = comp[(comp.judge == "llama") & (comp.a == ref) & comp.b.isin(bases) & (comp.direction == "reference_vs_baseline") & comp.model.isin(c3["primary_models"])]
    n_agree = sum(1 for r in _ll_raw.itertuples() for o in comp[comp.confirmatory].itertuples() if o.model == r.model and o.b == r.b and bool(o.noninferior_ci) == bool(r.noninferior_ci))
    P(f"\nJudge agreement: {n_agree} of eight confirmatory comparisons agree. The Sonnet INDETERMINATE under Llama rests on a single comparison — vs `semantic_retrieval@1024`, CI low −0.0316 against a −0.0300 margin, missed by 0.0016 — which passes under Holm adjustment. This is a borderline comparison falling on opposite sides of the margin, not a judge-reliability disagreement.\n")
    P("### Pooled (Sonnet + Haiku averaged within scenario first; secondary)\n")
    po = comp[(comp.direction == "pooled")].copy()
    P(md(po[["judge", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio"]].rename(columns={"b": "baseline", "q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "noninferior_ci": "NI (CI)", "tok_ratio": "tokens ref/base"}), "{:.4f}"))
    P("\n## 4. Decision (applied mechanically)\n")
    for mk in c3["primary_models"]:
        d = dec["primary"][mk]
        P(f"- **{disp[mk]}: {lab(d['verdict'])}.** Reference {d['reference_score']:.3f} at {d['reference_tokens']:.0f} tokens; best baseline `{d['best_baseline']}` {d['best_baseline_score']:.3f} at {d['best_baseline_tokens']:.0f} tokens (ratio {d['token_ratio_ref_over_best']:.2f}, need ≤ {c3['token_ratio_pass_max']} for PASS). Reference non-inferior to all four: CI {d['reference_noninferior_to_all_baselines_ci']}, Holm {d['reference_noninferior_to_all_baselines_holm']}. Best baseline non-inferior to reference: {d['best_baseline_noninferior_to_reference']}; its tokens ≤ 1.3× reference: {d['best_baseline_tokens_le_1.3x_reference']}.")
    P("\nPower note (handoff §4): with a per-scenario sd ≈ 0.21, a pooled ~2.6 pp superiority effect needs ≈ 520 scenarios at 80% power; this benchmark has 145. The PASS is a non-inferiority-plus-token-ratio result, not a powered superiority claim. Point estimates favour the reference on all eight confirmatory comparisons, and the CI excludes zero on "
      + ", ".join(f"{disp[r.model]} vs {r.b}" for r in comp[comp.confirmatory].itertuples() if r.q_ci_low > 0) + ".\n")
    P("## 5. Quality / token frontier (every method, every model; 95% cluster-bootstrap CIs on both axes)\n")
    P("![frontier](../f05-candidate-realism/results/check3/frontier.png)\n")
    fr = fro.copy(); fr["model"] = fr.model.map(disp)
    P(md(fr[["model", "method_label", "n", "context_tokens", "tok_ci_low", "tok_ci_high", "checklist_opus", "q_ci_low_opus", "q_ci_high_opus", "checklist_llama", "context_precision", "irrelevant_context_ratio", "leakage_opus", "leakage_llama"]].rename(columns={"method_label": "method", "context_tokens": "tokens", "tok_ci_low": "tok CI low", "tok_ci_high": "tok CI high", "checklist_opus": "checklist (Opus)", "q_ci_low_opus": "CI low", "q_ci_high_opus": "CI high", "checklist_llama": "checklist (Llama)", "context_precision": "precision", "irrelevant_context_ratio": "irrelevant ratio", "leakage_opus": "leakage (Opus)", "leakage_llama": "leakage (Llama)"})))
    P("\nWhere structure separates from retrieval regardless of the quality verdict: context precision 0.95 vs 0.43–0.49 and distractor leakage ≈ 1–4% vs 15–19% (Opus) for the reference against the retrieval/summary baselines, at 0.38–0.53 of their tokens.\n")
    P("## 6. Exploratory (labelled; no adjustment)\n")
    ex = comp[(comp.judge == "opus") & (comp.direction == "reference_vs_baseline") & (comp.a != ref) & comp.model.isin(c3["primary_models"]) & comp.b.isin(bases + ["full_history"])].copy(); ex["model"] = ex.model.map(disp)
    P("`candidate_oracle@10`, `candidate_oracle@5` and the oracle-optimistic `oracle_dag` against the same baselines (Opus):\n")
    P(md(ex[["model", "a", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "tok_ratio"]].rename(columns={"a": "reference", "b": "baseline", "q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "tok_ratio": "tokens ref/base"}), "{:.4f}"))
    P("\n### Per-family (reference − baseline, Opus; bootstrap within family; |Δ| ≤ 0.075 is inside the F0.5 noise floor and not reportable as signal)\n")
    fo = fam[(fam.judge == "opus") & fam.model.isin(c3["primary_models"])].copy()
    for mk in c3["primary_models"]:
        sub = fo[fo.model == mk]
        piv = sub.pivot(index="family", columns="b", values="q_diff").round(3)
        lo = sub.pivot(index="family", columns="b", values="q_ci_low").round(3); hi = sub.pivot(index="family", columns="b", values="q_ci_high").round(3)
        cells = piv.copy().astype(object)
        for f_ in piv.index:
            for b in piv.columns:
                v = piv.loc[f_, b]
                cells.loc[f_, b] = f"{v:+.3f} [{lo.loc[f_, b]:+.2f}, {hi.loc[f_, b]:+.2f}]" + ("" if abs(v) <= c3["per_family_noise_floor"] else " **")
        P(f"\n{disp[mk]} (** = outside the ±0.075 noise floor):\n"); P(md(cells.reset_index()))
    P("\n## 7. MiniMax M2.5 arm (secondary; Llama judge for the full table, Opus where it exists)\n")
    mm = comp[(comp.model == "response_c") & (comp.direction == "reference_vs_baseline") & (comp.a == ref)].copy()
    P(md(mm[["judge", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio"]].rename(columns={"b": "baseline", "q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "noninferior_ci": "NI (CI)", "tok_ratio": "tokens ref/base"}), "{:.4f}"))
    P(f"\nMechanical criterion applied to MiniMax (not part of the frozen confirmatory set): Opus {lab(dec['secondary_minimax']['opus']['verdict'])}; Llama {lab(dec['secondary_minimax']['llama']['verdict'])}. Note: the 32 off-route Opus calls all sit in this arm (§2).\n")
    if verb:
        s = verb["summary"]
        P("### Verbosity check (handoff §3.4)\n")
        P(f"{verb['n']} seeded `candidate_oracle@15` scenarios; the MiniMax answer truncated to the cl100k token length of Haiku's answer on the same scenario; original, truncated and Haiku answers all judged fresh by Llama 4 Maverick.\n")
        P(md(pd.DataFrame({"variant": list(s["checklist"].keys()), "checklist (Llama)": list(s["checklist"].values()), "answer tokens": [s["answer_tokens"][k] for k in s["checklist"]]})))
        P(f"\nThe confound as stated in the F0.5 review rests on MiniMax's ~482 *billed* output tokens per answer, which include its reasoning trace. Its visible answers are not longer than Haiku's: {s['answer_tokens']['minimax_original']:.0f} vs {s['answer_tokens']['haiku']:.0f} cl100k tokens on these 40 scenarios. Truncation therefore removes only a small tail.\n")
        o, t, c = verb["minimax_minus_haiku_original"], verb["minimax_minus_haiku_truncated"], verb["truncation_cost"]
        P(f"\nMiniMax − Haiku: original {o[0]:+.3f} [{o[1]:+.3f}, {o[2]:+.3f}]; truncated to Haiku's length {t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}]; cost of truncation {c[0]:+.3f} [{c[1]:+.3f}, {c[2]:+.3f}]. "
          + ("The margin survives length-matching." if t[1] > 0 else ("The margin shrinks but its point estimate stays positive; the CI includes zero at n=40." if t[0] > 0 else "The margin does not survive length-matching.")) + "\n")
    P("MiniMax's Bedrock per-token rate is still billed at the assumed upper bound ($0.60 / $2.40 per 1M); no console confirmation was available in this session.\n")
    P("## 8. Cost\n")
    P(f"Check 3 spend: **${L.total:.2f}** across {L.calls:,} calls ({L.tokens_in:,} input / {L.tokens_out:,} output tokens); estimate $3.2, warning $5, hard limit $10. Zero new Opus calls.\n")
    P(md(pd.DataFrame([{"purpose": k, "usd": round(v, 3)} for k, v in sorted(L.by_purpose.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P(""); P(md(pd.DataFrame([{"model": k, "usd": round(v, 3)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P("\n## 9. What this settles and does not (handoff §5)\n")
    P("It settles check 3 **on benchmark 1.1**: nine-turn histories, ~1,500 full-history tokens, where `semantic_retrieval@1024` keeps about two-thirds of the conversation and had 0.99–1.0 context recall in F0. Retrieval sees nearly everything the oracle sees in this regime, so a PASS here is a lower bound on the structured-context advantage and a null would have been weak evidence of comparability. It unblocks router work (R1.1), starting with the insufficiency detector; benchmark 1.2 (30–60 turn histories) remains required before any paper claim about long multi-topic conversations.\n")
    P("## 10. Assumptions and limitations\n")
    P("- Confirmatory-with-disclosure, per §0; one pooled point estimate was known before the thresholds were frozen.")
    P("- The frozen criterion's FAIL branch was unreachable given the arms in this design: it required a baseline non-inferior to the reference while using ≤ 1.3× its context tokens (≤ 614), and the cheapest baseline in the study uses 893 (1.89×). Only PASS and INDETERMINATE were reachable, and the PASS token condition held by construction. This check therefore establishes non-inferiority at a −0.03 margin plus a token ratio, not a superiority or a dominance result. Item 5 below adds the missing like-for-like retrieval arm as a sensitivity analysis.")
    P("- Opus 4.6 is the same vendor family as Sonnet and Haiku; the Llama replication is the cross-vendor control and is reported for every confirmatory comparison.")
    P("- `candidate_oracle@15` equals `oracle_dag` in context on 99.3% of scenarios on this benchmark, so the reference is effectively the oracle DAG re-answered; the comparison is oracle-vs-baseline in all but name.")
    P("- Non-determinism at temperature 0 (23 of 432 identical prompts gave identical answers) puts a floor of a few pp on per-family differences; per-family cells inside ±0.075 are not signal.")
    P("- MiniMax rows: rate unconfirmed, 32 off-route judge calls, reasoning tokens counted as output.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(A) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
