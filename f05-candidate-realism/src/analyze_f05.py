"""F0.5 analysis (handoff §4, plan §4.5): tables, paired bootstrap, retention, Pareto plot,
and the mechanical PASS / PIVOT decision against the frozen thresholds.

All quality comparisons use one judge (the adopted cheap judge): F0.5's own answers plus the
re-judged F0 full_history / oracle_dag baselines. F0's Opus verdicts appear only in the
judge-shift table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, f0_answers, f0_scores, load_manifest, method_label, read_jsonl  # noqa: E402

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
SCORES = ROOT / "results" / "scored" / "scores.jsonl"
TABLES = ROOT / "results" / "tables"
PLOTS = ROOT / "results" / "plots"
SEL = ["context_precision", "context_recall", "context_f1", "context_sufficiency", "irrelevant_context_ratio"]


def load(man: dict) -> pd.DataFrame:
    own = read_jsonl(ANSWERS)
    meths = set(man["candidate_oracle"]["rejudge_f0_methods"])
    base = [r for r in f0_answers().values() if r["method"] in meths and r["model_key"] in ("response_a", "response_b")]
    a = pd.DataFrame(own + base)
    a = a.drop_duplicates("key", keep="last")
    sc = {}
    for r in read_jsonl(SCORES):
        sc.setdefault(r["key"], r)
    # The adopted judge is Opus 4.6 (no cheap candidate passed calibration), so F0's existing Opus
    # verdicts on the full_history / oracle_dag baselines are the same judge and are used directly.
    jid = man["models"]["judge"]["id"] or ""
    if ".anthropic.claude-opus" in jid:
        for k, r in f0_scores().items():
            if k not in sc and ".anthropic.claude-opus" in r.get("judge_model", ""):
                sc[k] = r
    s = pd.DataFrame(list(sc.values())) if sc else pd.DataFrame(columns=["key"])
    keep = [c for c in ("key", "checklist_score", "all_required_satisfied", "distractor_leakage", "judge_model", "judge_prompt_variant", "judge_input_tokens", "judge_output_tokens") if c in s.columns]
    df = a.merge(s[keep], on="key", how="left")
    opus = f0_scores()
    df["opus_checklist_score"] = [opus[k]["checklist_score"] if k in opus else np.nan for k in df["key"]]
    df["method_label"] = [method_label(m, b) for m, b in zip(df["method"], df["budget"])]
    if "recall_fallback" not in df.columns:
        df["recall_fallback"] = np.nan
    df["recall_fallback"] = df["recall_fallback"].fillna(0).astype(int)
    return df


def boot(d: np.ndarray, n: int, rng) -> tuple[float, float, float]:
    idx = rng.integers(0, len(d), size=(n, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def paired(df, mk, a, b, metric, n, rng, families=None, mask_fn=None) -> dict | None:
    sub = df[df.model_key == mk]
    if families is not None:
        sub = sub[sub.family.isin(families)]
    pa = sub[sub.method_label == a]
    if mask_fn is not None:
        pa = pa[mask_fn(pa)]
    pa = pa.set_index("scenario_id")[metric]
    pb = sub[sub.method_label == b].set_index("scenario_id")[metric]
    common = pa.index.intersection(pb.index)
    pa, pb = pa.loc[common].astype(float), pb.loc[common].astype(float)
    ok = ~(pa.isna() | pb.isna())
    if ok.sum() < 2:
        return None
    mean, lo, hi = boot((pa[ok] - pb[ok]).to_numpy(), n, rng)
    return {"model": mk, "a": a, "b": b, "metric": metric, "n": int(ok.sum()), "mean_diff": mean, "ci_low": lo, "ci_high": hi,
            "families": ",".join(families) if families else "all"}


def main() -> None:
    man = load_manifest()
    thr = man["f05_decision_thresholds"]
    n_boot = man["analysis"]["bootstrap_resamples"]
    rng = np.random.default_rng(man["run"]["seed"])
    pk = man["candidate_generator"]["primary_k"]
    cand = f"candidate_oracle@{pk}"
    TABLES.mkdir(parents=True, exist_ok=True); PLOTS.mkdir(parents=True, exist_ok=True)
    df = load(man)
    jid = man["models"]["judge"]["id"] or ""
    print(f"{len(df)} instances, {df.checklist_score.notna().sum()} scored by {sorted(df.judge_model.dropna().unique())}, models {sorted(df.model_key.unique())}")
    df.drop(columns=[c for c in ("prompt", "system_prompt", "response", "pool_k", "gold_closure") if c in df.columns]).to_csv(TABLES / "per_instance.csv", index=False)

    # 1. summary per model × method (+ recall-holds-only view of the candidate oracle)
    view = df.copy()
    nf = df[(df.method == "candidate_oracle") & (df.recall_fallback == 0)].copy()
    nf["method_label"] = nf["method_label"] + "[recall-holds]"
    view = pd.concat([view, nf], ignore_index=True)
    metrics = ["context_tokens"] + SEL + ["checklist_score", "all_required_satisfied", "distractor_leakage", "recall_fallback", "input_tokens", "output_tokens", "answer_latency_s"]
    g = view.groupby(["model_key", "method_label"])
    summary = g[[m for m in metrics if m in view.columns]].mean()
    summary["n"] = g.size(); summary["n_scored"] = g["checklist_score"].count()
    summary["context_tokens_median"] = g["context_tokens"].median()
    full = summary.xs("full_history", level="method_label")["context_tokens"]
    summary["token_reduction_pct"] = [100 * (1 - r.context_tokens / full[m]) if m in full.index else np.nan for (m, _), r in summary.iterrows()]
    lo, hi = [], []
    for _, grp in g:
        v = grp["checklist_score"].dropna().to_numpy()
        if len(v) >= 2:
            _, l, h = boot(v, n_boot, rng); lo.append(l); hi.append(h)
        else:
            lo.append(np.nan); hi.append(np.nan)
    summary["checklist_ci_low"], summary["checklist_ci_high"] = lo, hi
    summary = summary.round(4)
    summary.to_csv(TABLES / "summary.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    print("\n== summary (adopted judge) ==")
    print(summary[["n", "n_scored", "context_tokens", "token_reduction_pct", "checklist_score", "checklist_ci_low", "checklist_ci_high", "context_sufficiency", "irrelevant_context_ratio", "distractor_leakage", "recall_fallback"]].to_string())

    # 2. pairwise paired bootstrap
    rows = []
    for mk in sorted(df.model_key.unique()):
        labels = sorted(df[(df.model_key == mk) & (df.method == "candidate_oracle")].method_label.unique(), key=lambda x: int(x.split("@")[1]))
        for cl in labels:
            for b in ("oracle_dag", "full_history"):
                for metric in ("checklist_score", "context_tokens"):
                    r = paired(df, mk, cl, b, metric, n_boot, rng)
                    if r: rows.append(r)
            r = paired(df, mk, cl, "full_history", "checklist_score", n_boot, rng, mask_fn=lambda d: d.recall_fallback == 0)
            if r: r["a"] = cl + "[recall-holds]"; rows.append(r)
            r = paired(df, mk, cl, "oracle_dag", "checklist_score", n_boot, rng, families=man["analysis"]["join_families"])
            if r: rows.append(r)
        r = paired(df, mk, "oracle_dag", "full_history", "checklist_score", n_boot, rng)
        if r: rows.append(r)
        r = paired(df, mk, "oracle_dag", "full_history", "context_tokens", n_boot, rng)
        if r: rows.append(r)
    comp = pd.DataFrame(rows).round(4)
    comp.to_csv(TABLES / "pairwise.csv", index=False)
    print("\n== pairwise (a minus b; mean diff [95% CI]) ==")
    print(comp.to_string(index=False) if len(comp) else "(nothing scored yet)")

    # 3. advantage retention (reported, not gating): (cand - full) / (dag - full), bootstrap over scenarios
    ret_rows = []
    for mk in sorted(df.model_key.unique()):
        sub = df[df.model_key == mk]
        piv = sub.pivot_table(index="scenario_id", columns="method_label", values="checklist_score")
        if not {cand, "oracle_dag", "full_history"} <= set(piv.columns):
            continue
        p = piv[[cand, "oracle_dag", "full_history"]].dropna()
        c, d, f = p[cand].to_numpy(), p["oracle_dag"].to_numpy(), p["full_history"].to_numpy()
        num, den = (c - f).mean(), (d - f).mean()
        idx = rng.integers(0, len(p), size=(n_boot, len(p)))
        nums, dens = (c - f)[idx].mean(axis=1), (d - f)[idx].mean(axis=1)
        ratios = np.where(np.abs(dens) > 1e-9, nums / dens, np.nan)
        ret_rows.append({"model": mk, "n": len(p), "cand_minus_full_pp": 100 * num, "dag_minus_full_pp": 100 * den,
                         "retention_pct": 100 * num / den if abs(den) > 1e-9 else np.nan,
                         "retention_ci_low": 100 * np.nanpercentile(ratios, 2.5), "retention_ci_high": 100 * np.nanpercentile(ratios, 97.5),
                         "denominator_ci_spans_zero": bool(np.percentile(dens, 2.5) <= 0 <= np.percentile(dens, 97.5))})
    ret = pd.DataFrame(ret_rows).round(3)
    ret.to_csv(TABLES / "retention.csv", index=False)
    print("\n== advantage retention (reported only) ==")
    print(ret.to_string(index=False) if len(ret) else "(n/a)")

    # 4. by family
    fam = df.pivot_table(index="family", columns=["model_key", "method_label"], values="checklist_score", aggfunc="mean").round(3)
    fam.to_csv(TABLES / "by_family_checklist_pivot.csv")
    fb = df[df.method == "candidate_oracle"].groupby(["family", "method_label"])["recall_fallback"].mean().unstack().round(3)
    fb.to_csv(TABLES / "by_family_fallback_rate.csv")
    ct = df[(df.family == "compound_turn")].copy()
    if len(ct):
        pools = {r["scenario_id"]: r for r in json.loads((ROOT / "results" / "raw" / "candidate_pools.json").read_text())}
        ct["variant"] = ct.scenario_id.map(lambda s: pools[s]["variant"])
        ct.pivot_table(index="variant", columns=["model_key", "method_label"], values="checklist_score", aggfunc="mean").round(3).to_csv(TABLES / "compound_turn_by_variant.csv")
    for mk in ("response_a", "response_b", "response_c"):
        if mk in fam.columns.get_level_values(0):
            print(f"\n== checklist by family ({mk}) =="); print(fam[mk].to_string())

    # 4b. context identity: how often the candidate oracle's selection equals the F0 oracle DAG's
    ident = []
    for mk in sorted(df.model_key.unique()):
        sub = df[df.model_key == mk]
        dag = sub[sub.method_label == "oracle_dag"].set_index("scenario_id")["selected_turn_ids"].map(tuple)
        for cl in sorted(sub[sub.method == "candidate_oracle"].method_label.unique(), key=lambda x: int(x.split("@")[1])):
            c = sub[sub.method_label == cl].set_index("scenario_id")
            common = c.index.intersection(dag.index)
            same = (c.loc[common, "selected_turn_ids"].map(tuple) == dag.loc[common]).mean()
            ident.append({"model": mk, "method_label": cl, "n": len(common), "same_context_as_oracle_dag": float(same),
                          "fallback_rate": float(c.loc[common, "recall_fallback"].mean())})
    pd.DataFrame(ident).round(4).to_csv(TABLES / "context_identity.csv", index=False)
    print("\n== context identity vs oracle_dag =="); print(pd.DataFrame(ident).round(3).to_string(index=False))

    # 5. judge shift: same answers, Opus (F0) vs adopted judge (skipped when the adopted judge is Opus itself)
    js = df[df.opus_checklist_score.notna() & df.checklist_score.notna()]
    if ".anthropic.claude-opus" in jid:
        js = js.iloc[0:0]
        (TABLES / "judge_shift.csv").unlink(missing_ok=True)
    if len(js):
        shift = js.groupby(["model_key", "method_label"]).agg(n=("key", "size"), opus_mean=("opus_checklist_score", "mean"), adopted_mean=("checklist_score", "mean"))
        shift["delta"] = shift.adopted_mean - shift.opus_mean
        shift = shift.round(4); shift.to_csv(TABLES / "judge_shift.csv")
        print("\n== judge shift on F0 baselines (Opus vs adopted) =="); print(shift.to_string())

    # 6. Pareto plot (same-judge arms only)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = {"response_a": "C0", "response_b": "C1", "response_c": "C2"}
    markers = {"response_a": "o", "response_b": "s", "response_c": "^"}
    for (mk, ml), r in summary.iterrows():
        if np.isnan(r["checklist_score"]) or "[recall-holds]" in ml:
            continue
        ax.scatter(r["context_tokens"], r["checklist_score"], marker=markers.get(mk, "o"), s=70, color=colors.get(mk, "k"),
                   label=man["models"][mk]["display"] if ml == "full_history" else None)
        ax.annotate(ml, (r["context_tokens"], r["checklist_score"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set_xscale("log"); ax.set_xlabel("average context tokens (log)"); ax.set_ylabel("mean checklist score (adopted judge)")
    ax.set_title("F0.5: candidate-realistic oracle vs oracle DAG vs full history"); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(PLOTS / "pareto.png", dpi=150)

    # 7. mechanical decision
    recall = json.loads((TABLES / "recall_summary.json").read_text())
    decisions = {"recall_gate": {"strict_recall_at_k": recall["strict_recall_at_primary_k_all"], "threshold": thr["min_candidate_recall_at_k"], "pass": recall["passes_recall_gate"]}}
    print("\n== decision ==")
    print(f"recall gate: strict Recall@{pk} = {recall['strict_recall_at_primary_k_all']:.3f} (need >= {thr['min_candidate_recall_at_k']}) -> {recall['passes_recall_gate']}")
    for mk in ("response_a", "response_b"):
        if mk not in summary.index.get_level_values(0):
            continue
        s = summary.loc[mk]
        if cand not in s.index or np.isnan(s.loc[cand, "checklist_score"]):
            decisions[mk] = "not enough scored data"; print(f"{mk}: not enough scored data"); continue
        q_pp = 100 * (s.loc[cand, "checklist_score"] - s.loc["full_history", "checklist_score"])
        tok = s.loc[cand, "token_reduction_pct"]
        q_ok, t_ok = q_pp >= -thr["quality_non_inferiority_margin_pp"], tok >= thr["min_token_reduction_pct"]
        verdict = "PASS" if (recall["passes_recall_gate"] and q_ok and t_ok) else "PIVOT"
        why = []
        if not recall["passes_recall_gate"]: why.append("candidate recall below threshold")
        if not q_ok: why.append(f"quality {q_pp:+.1f} pp vs full history below -{thr['quality_non_inferiority_margin_pp']} pp")
        if not t_ok: why.append(f"token reduction {tok:.1f}% below {thr['min_token_reduction_pct']}%")
        decisions[mk] = {"verdict": verdict, "quality_diff_pp": round(q_pp, 2), "token_reduction_pct": round(float(tok), 2),
                         "retention_pct": (float(ret[ret.model == mk].retention_pct.iloc[0]) if len(ret[ret.model == mk]) else None), "reasons": why}
        print(f"{mk}: {cand} vs full_history quality {q_pp:+.1f} pp (need >= -{thr['quality_non_inferiority_margin_pp']}) -> {q_ok}; "
              f"token reduction {tok:.1f}% (need >= {thr['min_token_reduction_pct']}) -> {t_ok}  ==> {verdict}")
    (TABLES / "decision.json").write_text(json.dumps(decisions, indent=2))


if __name__ == "__main__":
    main()
