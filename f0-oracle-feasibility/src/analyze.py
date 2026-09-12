"""Tables, Pareto plot, paired bootstrap comparisons, and the mechanical GO/PIVOT/STOP
decision (handoff §8 and §9). Reads results/raw/answers.jsonl + results/scored/scores.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import ROOT, load_manifest  # noqa: E402

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
SCORES = ROOT / "results" / "scored" / "scores.jsonl"
TABLES = ROOT / "results" / "tables"
PLOTS = ROOT / "results" / "plots"

SEL_COLS = ["context_precision", "context_recall", "context_f1", "context_sufficiency", "irrelevant_context_ratio"]


def method_label(method: str, budget) -> str:
    return method if budget is None or (isinstance(budget, float) and np.isnan(budget)) else f"{method}@{int(budget)}"


def load() -> pd.DataFrame:
    a = pd.DataFrame([json.loads(l) for l in ANSWERS.read_text().splitlines() if l.strip()])
    s = pd.DataFrame([json.loads(l) for l in SCORES.read_text().splitlines() if l.strip()]) if SCORES.exists() else pd.DataFrame(columns=["key"])
    keep = ["key", "checklist_score", "all_required_satisfied", "distractor_leakage", "judge_model", "judge_input_tokens", "judge_output_tokens"]
    df = a.merge(s[[c for c in keep if c in s.columns]], on="key", how="left")
    df["method_label"] = [method_label(m, b) for m, b in zip(df["method"], df["budget"])]
    return df


def paired_bootstrap(x: np.ndarray, y: np.ndarray, n: int, rng: np.random.Generator) -> tuple[float, float, float]:
    """Mean of (x - y) with a percentile CI over resampled scenario indices."""
    d = x - y
    idx = rng.integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def compare(df: pd.DataFrame, model_key: str, a: str, b: str, metric: str, n: int, rng, families=None) -> dict | None:
    sub = df[df.model_key == model_key]
    if families is not None:
        sub = sub[sub.family.isin(families)]
    pa = sub[sub.method_label == a].set_index("scenario_id")[metric]
    pb = sub[sub.method_label == b].set_index("scenario_id")[metric]
    common = pa.index.intersection(pb.index)
    pa, pb = pa.loc[common].astype(float), pb.loc[common].astype(float)
    mask = ~(pa.isna() | pb.isna())
    if mask.sum() < 2:
        return None
    mean, lo, hi = paired_bootstrap(pa[mask].to_numpy(), pb[mask].to_numpy(), n, rng)
    return {"model": model_key, "a": a, "b": b, "metric": metric, "n": int(mask.sum()),
            "mean_diff": mean, "ci_low": lo, "ci_high": hi, "families": ",".join(families) if families else "all"}


def main() -> None:
    manifest = load_manifest()
    thr = manifest["decision_thresholds"]
    n_boot = manifest["analysis"]["bootstrap_resamples"]
    join_fams = manifest["analysis"]["join_families"]
    rng = np.random.default_rng(manifest["run"]["seed"])
    TABLES.mkdir(parents=True, exist_ok=True); PLOTS.mkdir(parents=True, exist_ok=True)
    df = load()
    scored = df["checklist_score"].notna().sum()
    print(f"{len(df)} instances, {scored} scored, {df.scenario_id.nunique()} scenarios, models: {sorted(df.model_key.unique())}")

    # 1. per-instance table
    df.drop(columns=[c for c in ("prompt", "system_prompt", "response", "summary_text") if c in df.columns]).to_csv(TABLES / "per_instance.csv", index=False)

    # 2. aggregated summary
    metrics = ["context_tokens"] + SEL_COLS + ["checklist_score", "all_required_satisfied", "distractor_leakage", "input_tokens", "output_tokens", "answer_latency_s", "build_latency_s"]
    g = df.groupby(["model_key", "method_label"])
    summary = g[metrics].mean()
    summary["context_tokens_median"] = g["context_tokens"].median()
    summary["n"] = g.size()
    full_act = summary.xs("full_history", level="method_label")["context_tokens"]
    summary["token_reduction_pct"] = [100 * (1 - r.context_tokens / full_act[m]) for (m, _), r in summary.iterrows()]
    # bootstrap CI on checklist score per method
    lo, hi = [], []
    for (mk, ml), grp in g:
        v = grp["checklist_score"].dropna().to_numpy()
        if len(v) >= 2:
            idx = rng.integers(0, len(v), size=(n_boot, len(v)))
            ms = v[idx].mean(axis=1); lo.append(np.percentile(ms, 2.5)); hi.append(np.percentile(ms, 97.5))
        else:
            lo.append(np.nan); hi.append(np.nan)
    summary["checklist_ci_low"], summary["checklist_ci_high"] = lo, hi
    summary = summary.round(4)
    summary.to_csv(TABLES / "summary.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("\n== summary ==")
    print(summary[["n", "context_tokens", "token_reduction_pct", "checklist_score", "checklist_ci_low", "checklist_ci_high", "context_precision", "context_recall", "context_sufficiency", "irrelevant_context_ratio", "distractor_leakage"]].to_string())

    # 3. Pareto plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 6))
    markers = {"response_a": "o", "response_b": "s"}
    for (mk, ml), r in summary.iterrows():
        if np.isnan(r["checklist_score"]):
            continue
        ax.scatter(r["context_tokens"], r["checklist_score"], marker=markers.get(mk, "o"), s=70,
                   label=f"{manifest['models'][mk]['display']}" if ml == "full_history" else None,
                   color="C0" if mk == "response_a" else "C1")
        ax.annotate(ml, (r["context_tokens"], r["checklist_score"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set_xscale("log"); ax.set_xlabel("average context tokens (log)"); ax.set_ylabel("mean checklist score")
    ax.set_title("F0: quality vs context tokens, per method per model"); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(PLOTS / "pareto.png", dpi=150)

    # 4. by-family breakdown
    fam = df.groupby(["family", "model_key", "method_label"])[["checklist_score", "context_recall", "context_tokens", "distractor_leakage"]].mean().round(3)
    fam.to_csv(TABLES / "by_family.csv")
    fam_pivot = df.pivot_table(index=["family"], columns=["model_key", "method_label"], values="checklist_score", aggfunc="mean").round(2)
    fam_pivot.to_csv(TABLES / "by_family_checklist_pivot.csv")
    print("\n== checklist score by family (response_a) ==")
    if "response_a" in fam_pivot.columns.get_level_values(0):
        print(fam_pivot["response_a"].to_string())

    # 5. pairwise comparisons
    budgets = manifest["context_methods"]["window_budgets_tokens"]
    baselines = ["full_history"] + [f"{m}@{b}" for m in ("sliding_window", "rolling_summary", "semantic_retrieval") for b in budgets]
    rows = []
    for mk in sorted(df.model_key.unique()):
        for b in baselines:
            for metric in ("checklist_score", "context_tokens"):
                r = compare(df, mk, "oracle_dag", b, metric, n_boot, rng)
                if r: rows.append(r)
        r = compare(df, mk, "oracle_dag", "oracle_tree", "checklist_score", n_boot, rng, families=join_fams)
        if r: rows.append(r)
    comp = pd.DataFrame(rows).round(4)
    comp.to_csv(TABLES / "pairwise.csv", index=False)
    print("\n== pairwise (oracle_dag minus baseline; mean diff [95% CI]) ==")
    print(comp.to_string(index=False) if len(comp) else "(no scored data yet)")

    # 6. failure cases
    fails = []
    for _, r in df[(df.method == "oracle_dag") & (df.context_sufficiency == 0)].iterrows():
        fails.append({"type": "oracle_dag_insufficient", "scenario_id": r.scenario_id, "model": r.model_key, "note": f"selected {r.selected_turn_ids}"})
    for mk in df.model_key.unique():
        sub = df[df.model_key == mk]
        d = sub[sub.method_label == "oracle_dag"].set_index("scenario_id")["checklist_score"]
        f = sub[sub.method_label == "full_history"].set_index("scenario_id")["checklist_score"]
        for sid in d.index.intersection(f.index):
            if pd.notna(d[sid]) and pd.notna(f[sid]) and f[sid] >= d[sid] and f[sid] > 0 and d[sid] < 1:
                fails.append({"type": "full_history_ge_oracle_dag", "scenario_id": sid, "model": mk, "note": f"full={f[sid]:.2f} dag={d[sid]:.2f}"})
    pd.DataFrame(fails).to_csv(TABLES / "failure_cases.csv", index=False)
    print(f"\n{len(fails)} failure-case rows written")

    # 7. mechanical decision
    print("\n== decision check (per response model) ==")
    decisions = {}
    for mk in sorted(df.model_key.unique()):
        s = summary.loc[mk]
        if "oracle_dag" not in s.index or np.isnan(s.loc["oracle_dag", "checklist_score"]):
            print(f"{mk}: not enough scored data"); continue
        q_diff_pp = 100 * (s.loc["oracle_dag", "checklist_score"] - s.loc["full_history", "checklist_score"])
        tok_red = s.loc["oracle_dag", "token_reduction_pct"]
        join = comp[(comp.model == mk) & (comp.b == "oracle_tree")]
        join_adv = float(join.mean_diff.iloc[0]) if len(join) else float("nan")
        q_ok = q_diff_pp >= -thr["quality_non_inferiority_margin_pp"]
        t_ok = tok_red >= thr["min_token_reduction_pct"]
        j_ok = (join_adv > 0) if thr["join_advantage_required"] else True
        if q_ok and t_ok and j_ok:
            verdict = "GO"
        elif q_ok and t_ok and not j_ok:
            verdict = "PIVOT (DAG not better than tree on joins: simplify to tree-only)"
        elif t_ok and not q_ok:
            verdict = "PIVOT (tokens saved but quality below margin: revisit dependency semantics)"
        else:
            verdict = "STOP"
        decisions[mk] = verdict
        print(f"{mk}: quality diff vs full history = {q_diff_pp:+.1f} pp (need >= -{thr['quality_non_inferiority_margin_pp']}) -> {q_ok}; "
              f"token reduction = {tok_red:.1f}% (need >= {thr['min_token_reduction_pct']}) -> {t_ok}; "
              f"join advantage (DAG - tree, join families) = {join_adv:+.3f} -> {j_ok}  ==> {verdict}")
    (TABLES / "decision.json").write_text(json.dumps(decisions, indent=2))


if __name__ == "__main__":
    main()
