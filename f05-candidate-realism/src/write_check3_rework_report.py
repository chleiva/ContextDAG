"""Fill claude/CHECK3_REWORK_RESULTS.md (Check 3 Rework handoff §6) from results/check3/*."""
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
OUT = REPO / "docs" / "results" / "CHECK3_REWORK_RESULTS.md"


def md(df: pd.DataFrame, fmt: str = "{:.4f}") -> str:
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
    comp = pd.read_csv(C3 / "comparisons.csv"); before = pd.read_csv(C3 / "comparisons_before_rework.csv")
    fro = pd.read_csv(C3 / "frontier.csv")
    var = json.loads((C3 / "rework_variance.json").read_text()); ss = pd.read_csv(C3 / "rework_sample_size.csv")
    off = json.loads((C3 / "rework_offroute.json").read_text()) if (C3 / "rework_offroute.json").exists() else None
    L = ledger()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    ref = c3["reference_method"]
    A = []; P = A.append
    P("# Check 3 Rework — Results\n")
    P(f"Run date: {date.today().isoformat()}; generated at commit {commit}. Scope: the five items of the rework handoff, nothing else. `claude/CHECK3_RESULTS.md` updated in place per items 1 and 2 with a dated note at its top.\n")

    # ---- item 1
    P("## Item 1 — Pooled-row bug\n")
    P("**Defect confirmed.** The pooling routine averaged within scenario over every model with a verdict for *each arm separately*, so MiniMax (Opus verdicts on `candidate_oracle@15` but on none of the retrieval/summary arms) entered the reference mean and not the baselines'. **Fix:** the model set is now the intersection of models carrying verdicts for both arms, per judge, applied to both sides. Before/after:\n")
    m = before[before.direction == "pooled"][["judge", "b", "q_diff", "q_ci_low", "q_ci_high"]].merge(
        comp[comp.direction == "pooled"][["judge", "b", "q_diff", "q_ci_low", "q_ci_high", "pooled_models"]], on=["judge", "b"], suffixes=(" (old)", " (new)"))
    m["shift"] = m["q_diff (new)"] - m["q_diff (old)"]
    P(md(m.rename(columns={"b": "baseline"})))
    P("\nAcceptance: the four corrected Opus deltas match the handoff's expected values (+0.0279 / +0.0149 / +0.0290 / +0.0362 → observed +0.0279 / +0.0149 / +0.0290 / +0.0361); the Opus shift is the constant −0.0132; `semantic_retrieval@2048`'s pooled CI now spans zero; Llama pooled rows are unchanged; the per-model confirmatory table is byte-identical (verified by dataframe equality before regeneration).\n")
    P("**Regression guard** (`src/check3.py`, runs on every analysis): for every pooled row, assert that per-model rows exist for exactly the pooled model set, that all use the same scenario count, and that the pooled Δ equals the mean of the per-model Δs to within 1e-6. It passes on the corrected pipeline and fails on the old one.\n")

    # ---- item 2
    P("## Item 2 — Headline and criterion defect\n")
    P("Applied in `claude/CHECK3_RESULTS.md` (via the report generator, so the edits persist across regeneration): headline and §4 now read **PASS (non-inferiority + token ratio)** with the prescribed sentence; §10 carries the unreachable-FAIL bullet verbatim; the §3 judge-agreement paragraph is replaced by the prescribed text (seven of eight comparisons agree; the Sonnet INDETERMINATE rests on one comparison missed by 0.0016 that passes under Holm). The mechanical verdicts are unchanged. No numeric table was altered.\n")

    # ---- item 3
    P("## Item 3 — Variance decomposition on the 432 identical-prompt pairs\n")
    P("Pairs: `candidate_oracle@15` (F0.5 answer) vs `oracle_dag` (F0 answer) with byte-identical prompts, Opus verdicts on both; 144 pairs per response model. σ²_decoder = var(paired Δ)/2; σ²_total = per-scenario variance of `candidate_oracle@15` (the cluster bootstrap's unit); σ²_scenario = σ²_total − σ²_decoder. 5,000-resample bootstrap CIs.\n")
    rows = []
    for arm, r in var.items():
        rows.append({"arm": disp.get(arm, arm), "n pairs": r["n_pairs"], "σ²_decoder": r["sigma2_decoder"], "CI": f"[{r['sigma2_decoder_ci'][0]:.4f}, {r['sigma2_decoder_ci'][1]:.4f}]",
                     "σ²_total": r["sigma2_total"], "CI ": f"[{r['sigma2_total_ci'][0]:.4f}, {r['sigma2_total_ci'][1]:.4f}]",
                     "σ²_scenario": r["sigma2_scenario"], "CI  ": f"[{r['sigma2_scenario_ci'][0]:.4f}, {r['sigma2_scenario_ci'][1]:.4f}]",
                     "decoder share": r["decoder_share"], "share CI": f"[{r['decoder_share_ci'][0]:.2f}, {r['decoder_share_ci'][1]:.2f}]", "pairs with equal score": r["identical_score_pairs"]})
    P(md(pd.DataFrame(rows)))
    P("\nSample size for a 2.6 pp paired effect at 80% power, α = 0.05 two-sided, n = 7.84 σ_eff(k)² / 0.026², σ_eff(k) = √(σ²_scenario + σ²_decoder / k):\n")
    ss2 = ss.copy(); ss2["arm"] = ss2.arm.map(lambda a: disp.get(a, a))
    P(md(ss2.rename(columns={"k_samples_per_cell": "k samples per cell", "sigma_eff": "σ_eff", "n_scenarios_for_2.6pp_80pct_power": "scenarios needed"}), "{:.3f}"))
    pl = var["pooled"]
    P(f"\n**Which lever buys power.** Decoder noise is {100 * pl['decoder_share']:.0f}% of per-scenario variance (pooled). Repeating each cell k times can remove at most that share: from k=1 to k=5 the required scenario count falls only from {ss[(ss.arm == 'pooled') & (ss.k_samples_per_cell == 1)].iloc[0, 3]:.0f} to {ss[(ss.arm == 'pooled') & (ss.k_samples_per_cell == 5)].iloc[0, 3]:.0f} (−22%) while multiplying answer and judge cost by 5. "
      "Adding scenarios reduces the standard error as 1/√n with no ceiling, at one answer per cell: reaching the k=1 target of ≈460 scenarios means ≈3.2× the current 145, i.e. ≈3.2× the per-phase answer/judge cost (≈ $1 of Llama judging plus cheap-model answers per 145 scenarios per arm), versus 5× the same cost for a 22% gain from resampling. "
      "Longer histories (benchmark 1.2) act on the effect size, not the variance: at the F0/F0.5 effect of ≈2.6 pp none of these options is cheap, whereas an effect of 5 pp needs ≈125 scenarios at k=1 (7.84 × 0.199² / 0.05²) and 9 pp needs ≈38. Per dollar: **longer histories first, then more scenarios, and resampling last.**\n")
    P("Caveat: σ²_decoder is estimated on the `candidate_oracle@15` / `oracle_dag` arm only (the only arm with identical-prompt repeats) and is assumed to transfer to the other arms; that assumption is untested here.\n")

    # ---- item 4
    P("## Item 4 — Re-judged off-route MiniMax instances\n")
    if off:
        o, n = off["minimax_cand15_vs_full_old"], off["minimax_cand15_vs_full_new"]
        P(f"{off['n_rejudged']} of {off.get('n_offroute', 32)} instances re-judged on `{off['route']}` (route recorded per record in `results/scored/check3_rework_opus.jsonl`). {off['changed_verdicts']} of {off['n_rejudged']} checklist scores changed; mean |change| {off['mean_abs_score_change']:.3f}."
          + (f" Not re-judged (Opus returned no verdict twice; old verdict retained): {', '.join(f['key'] for f in off['not_rejudged'])}." if off.get("not_rejudged") else "") + "\n")
        P(md(pd.DataFrame([{"version": "old (mixed routes)", "n": o["n"], "Δ checklist": o["q_diff"], "CI low": o["ci_low"], "CI high": o["ci_high"], "CI excludes 0": o["ci_low"] > 0},
                           {"version": "new (all primary route)", "n": n["n"], "Δ checklist": n["q_diff"], "CI low": n["ci_low"], "CI high": n["ci_high"], "CI excludes 0": n["ci_low"] > 0}])))
        P(("\nThe CI still excludes zero after re-judging." if n["ci_low"] > 0 else "\nThe CI no longer excludes zero after re-judging; nothing else was adjusted.") + " This row is the MiniMax Opus `candidate_oracle@15` vs `full_history` comparison (secondary arm).\n")
    else:
        P("Not run.\n")

    # ---- item 5
    P("## Item 5 — `semantic_retrieval@512` sensitivity arm (exploratory, Llama-judged)\n")
    P("Same retriever, embedding model (all-mpnet-base-v2) and turn-level selection as `@1024`/`@2048`; only the budget changes. 145 answers each for Sonnet 4.6, Haiku 4.5 and MiniMax M2.5, judged by Llama 4 Maverick. Not added to the frozen confirmatory set; no Opus verdicts.\n")
    r512 = comp[(comp.judge == "llama") & (comp.a == ref) & (comp.b == "semantic_retrieval@512") & (comp.direction == "reference_vs_baseline")].copy()
    r512["model"] = r512.model.map(disp)
    P(md(r512[["model", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio", "tok_ratio_ci_low", "tok_ratio_ci_high"]].rename(columns={"q_diff": "Δ checklist (ref − @512)", "q_ci_low": "CI low", "q_ci_high": "CI high", "noninferior_ci": "ref NI to @512", "tok_ratio": "tokens ref/@512", "tok_ratio_ci_low": "ratio CI low", "tok_ratio_ci_high": "ratio CI high"})))
    rev = comp[(comp.judge == "llama") & (comp.b == ref) & (comp.a == "semantic_retrieval@512")].copy()
    if len(rev):
        rev["model"] = rev.model.map(disp)
        P("\nReverse direction (is `@512` non-inferior to the reference at −0.03?):\n")
        P(md(rev[["model", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio"]].rename(columns={"q_diff": "Δ (@512 − ref)", "q_ci_low": "CI low", "q_ci_high": "CI high", "noninferior_ci": "@512 NI to ref", "tok_ratio": "tokens @512/ref"})))
    f512 = fro[fro.method_label == "semantic_retrieval@512"].copy(); f512["model"] = f512.model.map(disp)
    P("\nFrontier row (added to §5 of `CHECK3_RESULTS.md`):\n")
    P(md(f512[["model", "n", "context_tokens", "tok_ci_low", "tok_ci_high", "checklist_llama", "q_ci_low_llama", "q_ci_high_llama", "context_precision", "irrelevant_context_ratio", "leakage_llama"]].rename(columns={"context_tokens": "tokens", "checklist_llama": "checklist (Llama)", "q_ci_low_llama": "CI low", "q_ci_high_llama": "CI high", "context_precision": "precision", "irrelevant_context_ratio": "irrelevant ratio", "leakage_llama": "leakage (Llama)"}), "{:.3f}"))
    # fixed interpretation
    competitive = bool(len(rev)) and all(bool(x) for x in rev.noninferior_ci) and all(x <= c3["token_ratio_fail_max"] for x in rev.tok_ratio)
    n_worse = int((r512.q_ci_low > 0).sum()); n_models = len(r512)
    P("\n**Interpretation (fixed in advance):** ")
    P(f"Condition (a), `@512` non-inferior to the reference at −0.03 and within 1.3× its tokens: **{'met' if competitive else 'not met'}** — the reverse-direction lower CI bounds are " + ", ".join(f"{m} {lo:+.3f}" for m, lo in zip(rev.model, rev.q_ci_low)) + f", all below −0.03, at a token ratio of ≈1.0. Condition (b), `@512` materially worse than the reference: the reference's advantage has a CI excluding zero on {n_worse} of {n_models} models (" + ", ".join(f"{m} {d:+.3f} [{lo:+.3f}, {hi:+.3f}]" for m, d, lo, hi in zip(r512.model, r512.q_diff, r512.q_ci_low, r512.q_ci_high)) + ").\n")
    if competitive:
        P("Recorded verbatim: `@512` is non-inferior to the reference and within 1.3× its tokens, so retrieval is competitive at matched budget on benchmark 1.1. It does not overturn the recorded check-3 PASS, which stands under its frozen criterion; it means **benchmark 1.2 must re-test check 3 with the full retrieval budget sweep (256/512/1024/2048) under a criterion whose FAIL branch is reachable.**\n")
    else:
        P("Recorded verbatim, since (a) is not met: `@512` is **materially worse than the reference** — retrieval was tried at the oracle's budget and could not match it — so the token-ratio result is strengthened, and benchmark 1.2 still runs the sweep, but without the check-3 conclusion in doubt."
          + (" Qualification, recorded in §7 rather than resolved here: the handoff's two interpretations did not anticipate a split result; (b) is established on the models whose CI excludes zero and is directional on the remaining one, on which the point estimate favours the reference but the interval includes zero." if n_worse < n_models else "") + "\n")

    # ---- §7 and ledger
    P("## 7. Anything else found (recorded, not fixed)\n")
    P("- **Haiku `three_way_join` +0.000 against all five baselines:** inspected. Not a saturated checklist. Haiku's per-scenario scores vary (1.00, 0.75, 0.25, 1.00, 1.00, 1.00, 1.00, 1.00) but are identical across `candidate_oracle@{5,10,15}`, `full_history`, `oracle_dag`, both `rolling_summary` and both `semantic_retrieval` budgets, and differ only for `oracle_tree` (and one `sliding_window@1024` cell). These eight histories are 8–12 turns, so every one of those contexts contains the entire gold closure, and Haiku returns the same verdict pattern regardless of packaging. `three_way_join_003` scores 0.25 under every context including the oracle: at least one of its required checklist items is not satisfiable by Haiku from any context on this benchmark, which is worth a look when benchmark 1.2 regenerates the family. Sonnet's scores vary across methods on the same scenarios.")
    P("- `claude/CHECK3_Analysis_and_Recommendations.md`, listed as required reading, is not in the repository.")
    P("- Item 5's two pre-fixed interpretations assume a uniform outcome across models. The observed outcome is split: `@512` fails non-inferiority to the reference on all three models (so (a) is excluded), and the reference's advantage over `@512` has a CI excluding zero on Sonnet and MiniMax but not on Haiku (+0.032 [−0.009, +0.074]). Interpretation (b) was recorded with that qualification; whether Haiku's interval should count as 'materially worse' is a judgement the handoff reserves, and is left here.")
    P("- The reported variance-decomposition field previously labelled `identical_answer_pairs` counts pairs with equal *scores* (336 of 432), not identical answers (23 of 432); it is now named `identical_score_pairs`.")
    P("- In the F0.5 answer runner, `--dry-run` still triggers rolling-summary generation for models without a cached summary (it does not special-case summaries the way F0's runner did); harmless here because summaries are cached, but a dry run is not free for a new model.\n")
    import glob
    import re
    unledgered = sum(len(re.findall(r"no price for model", open(f).read())) for f in glob.glob(str(ROOT / "results" / "raw" / "rework_512_answers.log")))
    P("## 8. Ledger\n")
    if unledgered:
        P(f"Disclosure: {unledgered} Sonnet/Haiku answer calls in item 5 succeeded on the `global.` inference profile (region fallback under throttling) but were rejected by the ledger, which did not yet know that profile spelling, so they were billed by AWS (≈ ${unledgered * 0.0045:.2f} at the mean answer cost) and neither recorded nor kept; the answers were regenerated after adding the profile prices and a same-model price fallback to `f05_cost.price`.\n")
    P(f"Rework spend (check-3 ledger, incremental): items 1–3 $0; item 4 ${L.by_purpose.get('rework-opus', 0):.2f} (32 Opus calls, the sole waiver); item 5 ≈ ${L.total - 3.06 - L.by_purpose.get('rework-opus', 0):.2f} (435 answers incl. the 113 regenerated, plus Llama judging). Check-3 ledger total after rework: **${L.total:.2f}** (before rework $3.06, so the rework cost ${L.total - 3.06:.2f} against its $2.15 estimate); rework warning $4 / hard limit $8 never approached.\n")
    P(md(pd.DataFrame([{"purpose": k, "usd": round(v, 3)} for k, v in sorted(L.by_purpose.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P(""); P(md(pd.DataFrame([{"model": k, "usd": round(v, 3)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    OUT.write_text("\n".join(A) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
