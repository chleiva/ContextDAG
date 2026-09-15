"""Check 3 — retrieval/compression comparability (check3-handoof.md). Pure analysis, no LLM calls.

Data: F0 answers + Opus scores (a/b, all methods), F0.5 answers + Opus scores (candidate_oracle
arms, MiniMax arm), Llama 4 Maverick replication verdicts (results/scored/check3_llama_scores.jsonl).

Statistics (handoff §2): paired differences within scenario × model × judge; cluster bootstrap over
scenario ids (10,000); pooled = average within scenario first; one-sided non-inferiority p-values
with Holm over the four confirmatory comparisons per model; per-family bootstrap CIs read against
the 0.075 noise floor; token comparison as mean difference and ratio of means.

Outputs: results/check3/{comparisons,per_family,frontier,minimax}.csv, frontier.png, decision.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, f0_answers, f0_scores, load_manifest, method_label, read_jsonl  # noqa: E402

OUT = ROOT / "results" / "check3"
LLAMA = ROOT / "results" / "scored" / "check3_llama_scores.jsonl"
F05_ANS = ROOT / "results" / "raw" / "answers.jsonl"
F05_SC = ROOT / "results" / "scored" / "scores.jsonl"
JUDGES = ["opus", "llama"]


def load() -> pd.DataFrame:
    rows = {}
    for k, r in f0_answers().items():
        rows[k] = r
    for r in read_jsonl(F05_ANS):
        rows[r["key"]] = r
    opus = dict(f0_scores())
    for r in read_jsonl(F05_SC):
        opus.setdefault(r["key"], r)
    llama = {}
    for r in read_jsonl(LLAMA):
        llama.setdefault(r["key"], r)
    out = []
    for k, r in rows.items():
        o, l = opus.get(k), llama.get(k)
        out.append({"key": k, "scenario_id": r["scenario_id"], "family": r["family"], "model_key": r["model_key"],
                    "method_label": method_label(r["method"], r["budget"]), "context_tokens": r["context_tokens"],
                    "context_precision": r.get("context_precision"), "irrelevant_context_ratio": r.get("irrelevant_context_ratio"),
                    "output_tokens": r.get("output_tokens"),
                    "checklist_opus": o["checklist_score"] if o else np.nan, "leakage_opus": (o.get("distractor_leakage") if o else np.nan),
                    "checklist_llama": l["checklist_score"] if l else np.nan, "leakage_llama": (l.get("distractor_leakage") if l else np.nan)})
    return pd.DataFrame(out)


def cluster_boot(d: np.ndarray, n: int, rng) -> np.ndarray:
    """Means of `d` (one value per scenario) over resampled scenario ids."""
    idx = rng.integers(0, len(d), size=(n, len(d)))
    return d[idx].mean(axis=1)


def paired(df: pd.DataFrame, mk, a: str, b: str, judge: str, n: int, rng, margin: float, families=None, pooled=False) -> dict | None:
    col = f"checklist_{judge}"
    sub = df if mk is None else df[df.model_key == mk]
    if families is not None:
        sub = sub[sub.family.isin(families)]
    if pooled:   # average within scenario across models first
        pa = sub[sub.method_label == a].groupby("scenario_id")[[col, "context_tokens"]].mean()
        pb = sub[sub.method_label == b].groupby("scenario_id")[[col, "context_tokens"]].mean()
    else:
        pa = sub[sub.method_label == a].set_index("scenario_id")[[col, "context_tokens"]]
        pb = sub[sub.method_label == b].set_index("scenario_id")[[col, "context_tokens"]]
    common = pa.index.intersection(pb.index)
    pa, pb = pa.loc[common], pb.loc[common]
    ok = ~(pa[col].isna() | pb[col].isna())
    if ok.sum() < 5:
        return None
    dq = (pa[col] - pb[col])[ok].to_numpy(dtype=float)
    ta, tb = pa["context_tokens"][ok].to_numpy(dtype=float), pb["context_tokens"][ok].to_numpy(dtype=float)
    bq = cluster_boot(dq, n, rng)
    idx = rng.integers(0, len(ta), size=(n, len(ta)))
    br = ta[idx].mean(axis=1) / tb[idx].mean(axis=1)
    bt = (ta - tb)[idx].mean(axis=1)
    p_ni = float(np.mean(bq <= margin))          # one-sided: H0 "a is inferior to b by more than the margin"
    return {"model": mk or "pooled", "judge": judge, "a": a, "b": b, "n": int(ok.sum()), "families": ",".join(families) if families else "all",
            "q_diff": float(dq.mean()), "q_ci_low": float(np.percentile(bq, 2.5)), "q_ci_high": float(np.percentile(bq, 97.5)),
            "p_noninferior": p_ni, "noninferior_ci": bool(np.percentile(bq, 2.5) >= margin),
            "tok_diff": float((ta - tb).mean()), "tok_diff_ci_low": float(np.percentile(bt, 2.5)), "tok_diff_ci_high": float(np.percentile(bt, 97.5)),
            "tok_ratio": float(ta.mean() / tb.mean()), "tok_ratio_ci_low": float(np.percentile(br, 2.5)), "tok_ratio_ci_high": float(np.percentile(br, 97.5))}


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps); m = len(ps); adj = [0.0] * m; running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * ps[i]); adj[i] = min(1.0, running)
    return adj


def main() -> None:
    man = load_manifest(); c3 = man["check3"]
    n_boot, margin = c3["bootstrap_resamples"], c3["non_inferiority_margin"]
    rng = np.random.default_rng(man["run"]["seed"])
    ref, bases = c3["reference_method"], c3["confirmatory_baselines"]
    OUT.mkdir(parents=True, exist_ok=True)
    df = load()
    df.to_csv(OUT / "instances.csv", index=False)
    print(f"{len(df)} instances; opus-scored {df.checklist_opus.notna().sum()}, llama-scored {df.checklist_llama.notna().sum()}")

    # ---- confirmatory + exploratory paired comparisons
    rows = []
    for judge in JUDGES:
        for mk in ["response_a", "response_b", "response_c"]:
            for a in [ref, "candidate_oracle@10", "candidate_oracle@5", "oracle_dag"]:
                for b in bases + ["full_history", "sliding_window@1024", "sliding_window@2048"]:
                    r = paired(df, mk, a, b, judge, n_boot, rng, margin)
                    if r:
                        r["confirmatory"] = bool(a == ref and b in bases and mk in c3["primary_models"] and judge == "opus"); rows.append(r)
                # reverse direction for the FAIL arm of the criterion (is the baseline non-inferior to the reference?)
                if a == ref:
                    for b in bases:
                        r = paired(df, mk, b, a, judge, n_boot, rng, margin)
                        if r:
                            r["confirmatory"] = False; r["direction"] = "baseline_vs_reference"; rows.append(r)
        for b in bases:
            r = paired(df, None, ref, b, judge, n_boot, rng, margin, pooled=True)
            if r:
                r["confirmatory"] = False; r["direction"] = "pooled"; rows.append(r)
    comp = pd.DataFrame(rows)
    comp["direction"] = comp.get("direction", pd.Series(["reference_vs_baseline"] * len(comp))).fillna("reference_vs_baseline")
    # Holm over the four confirmatory comparisons per model (and the same set under the replication judge, reported separately)
    comp["p_holm"] = np.nan; comp["noninferior_holm"] = pd.Series([None] * len(comp), dtype=object)
    for judge in JUDGES:
        for mk in c3["primary_models"]:
            m = (comp.judge == judge) & (comp.model == mk) & (comp.a == ref) & comp.b.isin(bases) & (comp.direction == "reference_vs_baseline")
            if m.sum() == len(bases):
                adj = holm(comp.loc[m, "p_noninferior"].tolist())
                comp.loc[m, "p_holm"] = adj; comp.loc[m, "noninferior_holm"] = [x < 0.05 for x in adj]
    comp.round(4).to_csv(OUT / "comparisons.csv", index=False)

    # ---- per-family (reference vs each baseline, per model, Opus and Llama)
    fam_rows = []
    for judge in JUDGES:
        for mk in ["response_a", "response_b", "response_c"]:
            for b in bases + ["full_history"]:
                for fam in sorted(df.family.unique()):
                    r = paired(df, mk, ref, b, judge, 2000, rng, margin, families=[fam])
                    if r:
                        r["family"] = fam; r["within_noise_floor"] = bool(abs(r["q_diff"]) <= c3["per_family_noise_floor"]); fam_rows.append(r)
    pd.DataFrame(fam_rows).round(4).to_csv(OUT / "per_family.csv", index=False)

    # ---- frontier: every method × model, means with cluster-bootstrap CIs on both axes
    fr = []
    for (mk, ml), g in df.groupby(["model_key", "method_label"]):
        g = g.drop_duplicates("scenario_id")
        rec = {"model": mk, "method_label": ml, "n": len(g), "context_tokens": g.context_tokens.mean(),
               "context_precision": g.context_precision.mean(), "irrelevant_context_ratio": g.irrelevant_context_ratio.mean(),
               "output_tokens": g.output_tokens.mean()}
        t = g.context_tokens.to_numpy(dtype=float); bt = cluster_boot(t, n_boot, rng)
        rec["tok_ci_low"], rec["tok_ci_high"] = float(np.percentile(bt, 2.5)), float(np.percentile(bt, 97.5))
        for judge in JUDGES:
            v = g[f"checklist_{judge}"].dropna().to_numpy(dtype=float)
            rec[f"n_{judge}"] = len(v)
            if len(v) >= 5:
                bq = cluster_boot(v, n_boot, rng)
                rec[f"checklist_{judge}"], rec[f"q_ci_low_{judge}"], rec[f"q_ci_high_{judge}"] = float(v.mean()), float(np.percentile(bq, 2.5)), float(np.percentile(bq, 97.5))
                rec[f"leakage_{judge}"] = float(g[f"leakage_{judge}"].dropna().mean()) if g[f"leakage_{judge}"].notna().any() else np.nan
        fr.append(rec)
    frontier = pd.DataFrame(fr).round(4)
    frontier.to_csv(OUT / "frontier.csv", index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    disp = {k: man["models"][k]["display"] for k in ("response_a", "response_b", "response_c")}
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2), sharey=True)
    for ax, mk in zip(axes, ["response_a", "response_b", "response_c"]):
        sub = frontier[(frontier.model == mk) & frontier.checklist_opus.notna()]
        for _, r in sub.iterrows():
            ax.errorbar(r.context_tokens, r.checklist_opus, xerr=[[r.context_tokens - r.tok_ci_low], [r.tok_ci_high - r.context_tokens]],
                        yerr=[[r.checklist_opus - r.q_ci_low_opus], [r.q_ci_high_opus - r.checklist_opus]], fmt="o", ms=5, capsize=2,
                        color="C3" if r.method_label.startswith("candidate_oracle") else ("C0" if r.method_label.startswith("oracle") else "C7"))
            ax.annotate(r.method_label, (r.context_tokens, r.checklist_opus), fontsize=6.5, xytext=(3, 3), textcoords="offset points")
        ax.set_xscale("log"); ax.set_title(f"{disp[mk]} (Opus 4.6 judge)"); ax.set_xlabel("mean context tokens (log), 95% CI"); ax.grid(alpha=.3)
    axes[0].set_ylabel("mean checklist score, 95% cluster-bootstrap CI")
    fig.suptitle("Check 3: quality / token frontier, benchmark 1.1, 145 scenarios per point"); fig.tight_layout()
    fig.savefig(OUT / "frontier.png", dpi=150)

    # ---- mechanical decision per model, under each judge
    def decide(mk: str, judge: str) -> dict:
        sub = comp[(comp.model == mk) & (comp.judge == judge)]
        fro = frontier[frontier.model == mk].set_index("method_label")
        col = f"checklist_{judge}"
        if any(b not in fro.index or np.isnan(fro.loc[b, col]) for b in bases) or ref not in fro.index:
            return {"verdict": "insufficient data"}
        best = max(bases, key=lambda b: fro.loc[b, col])
        fwd = {r.b: r for r in sub[(sub.a == ref) & (sub.direction == "reference_vs_baseline")].itertuples()}
        rev = {r.a: r for r in sub[(sub.b == ref) & (sub.direction == "baseline_vs_reference")].itertuples()}
        if any(b not in fwd or b not in rev for b in bases):
            return {"verdict": "insufficient data"}
        ni_ref_all = all(fwd[b].noninferior_ci for b in bases)
        ni_ref_all_holm = all(bool(fwd[b].noninferior_holm) for b in bases) if judge == "opus" and mk in c3["primary_models"] else None
        tok_ref, tok_best = fro.loc[ref, "context_tokens"], fro.loc[best, "context_tokens"]
        pass_tokens = tok_ref <= c3["token_ratio_pass_max"] * tok_best
        fail_ni = bool(rev[best].noninferior_ci)
        fail_tokens = tok_best <= c3["token_ratio_fail_max"] * tok_ref
        if fail_ni and fail_tokens:
            verdict = "FAIL (retrieval/compression comparable)"
        elif ni_ref_all and pass_tokens:
            verdict = "PASS (structured context retains a distinct advantage)"
        else:
            verdict = "INDETERMINATE"
        return {"verdict": verdict, "best_baseline": best, "best_baseline_score": float(fro.loc[best, col]), "reference_score": float(fro.loc[ref, col]),
                "reference_tokens": float(tok_ref), "best_baseline_tokens": float(tok_best), "token_ratio_ref_over_best": float(tok_ref / tok_best),
                "reference_noninferior_to_all_baselines_ci": bool(ni_ref_all), "reference_noninferior_to_all_baselines_holm": ni_ref_all_holm,
                "reference_tokens_le_0.7x_best": bool(pass_tokens), "best_baseline_noninferior_to_reference": fail_ni, "best_baseline_tokens_le_1.3x_reference": bool(fail_tokens),
                "per_baseline": {b: {"q_diff": fwd[b].q_diff, "ci": [fwd[b].q_ci_low, fwd[b].q_ci_high], "p_holm": (None if pd.isna(fwd[b].p_holm) else float(fwd[b].p_holm)), "tok_ratio_ref_over_base": fwd[b].tok_ratio} for b in bases}}

    decision = {"frozen": {k: c3[k] for k in ("non_inferiority_margin", "token_ratio_fail_max", "token_ratio_pass_max", "reference_method", "confirmatory_baselines")},
                "primary": {mk: decide(mk, "opus") for mk in c3["primary_models"]},
                "replication_llama": {mk: decide(mk, "llama") for mk in c3["primary_models"]},
                "secondary_minimax": {"opus": decide("response_c", "opus"), "llama": decide("response_c", "llama")}}
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, default=float))

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("\n== confirmatory (Opus, reference vs baseline; q_diff = ref - base) ==")
    print(comp[comp.confirmatory][["model", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "p_noninferior", "p_holm", "noninferior_ci", "noninferior_holm", "tok_ratio", "tok_ratio_ci_low", "tok_ratio_ci_high"]].round(4).to_string(index=False))
    print("\n== same under Llama ==")
    print(comp[(comp.judge == "llama") & (comp.a == ref) & comp.b.isin(bases) & (comp.direction == "reference_vs_baseline") & comp.model.isin(c3["primary_models"])][["model", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "noninferior_ci", "tok_ratio"]].round(4).to_string(index=False))
    print("\n== frontier (Opus) ==")
    print(frontier[["model", "method_label", "n", "context_tokens", "checklist_opus", "q_ci_low_opus", "q_ci_high_opus", "checklist_llama", "context_precision", "irrelevant_context_ratio", "leakage_opus"]].to_string(index=False))
    print("\n== decision ==")
    for mk in c3["primary_models"]:
        print(mk, "opus:", decision["primary"][mk]["verdict"], "| llama:", decision["replication_llama"][mk]["verdict"])
    print("minimax:", decision["secondary_minimax"]["opus"]["verdict"], "| llama:", decision["secondary_minimax"]["llama"]["verdict"])


if __name__ == "__main__":
    main()
