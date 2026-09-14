"""Candidate Recall@k (handoff §2.4, spec §9.4) from results/raw/candidate_pools.json. No LLM.

Per scenario and k in the sweep: strict recall (every turn in the gold ancestor closure is in the
size-k pool) and fractional recall. Aggregated overall (145), excluding new_root (empty closure,
vacuous 1.0), by family, by compound_turn variant, and for the long families where k=15 binds.
Per-source ablation re-ranks the pool with one source removed. Bootstrap CIs over scenarios.

Writes results/tables/recall_by_k.csv, recall_by_family.csv, recall_variant.csv,
recall_ablation.csv, recall_misses.csv, recall_summary.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidates import POOLS, SOURCES, rank_pool  # noqa: E402
from f0_bridge import ROOT, load_manifest  # noqa: E402

TABLES = ROOT / "results" / "tables"


def k_label(k) -> str:
    return "uncapped" if k is None else str(k)


def pool_at(rec: dict, k, exclude: set[str] | None = None) -> list[str]:
    ranked = rank_pool(rec["pool"], exclude) if exclude else rec["ranked"]
    return ranked if k is None else ranked[:k]


def recall_row(rec: dict, k, exclude: set[str] | None = None) -> dict:
    pool = set(pool_at(rec, k, exclude))
    gold = rec["gold_closure"]
    found = [g for g in gold if g in pool]
    return {"scenario_id": rec["scenario_id"], "family": rec["family"], "variant": rec["variant"], "k": k_label(k),
            "n_history": rec["n_history"], "pool_size": len(pool), "pool_frac_of_history": len(pool) / rec["n_history"],
            "cap_binds": int(k is not None and rec["n_history"] > k), "n_gold": len(gold), "n_found": len(found),
            "k_feasible": int(k is None or k >= len(gold)),   # a pool of size k cannot hold a closure larger than k
            "strict": int(len(found) == len(gold)), "fractional": (len(found) / len(gold)) if gold else 1.0,
            "missing": ",".join(g for g in gold if g not in pool)}


def boot_ci(v: np.ndarray, n: int, rng) -> tuple[float, float]:
    if len(v) < 2:
        return float("nan"), float("nan")
    idx = rng.integers(0, len(v), size=(n, len(v)))
    m = v[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main() -> None:
    man = load_manifest()
    cfg = man["candidate_generator"]
    n_boot = man["analysis"]["bootstrap_resamples"]
    long_fams = man["analysis"]["long_families"]
    rng = np.random.default_rng(man["run"]["seed"])
    recs = json.loads(POOLS.read_text())
    TABLES.mkdir(parents=True, exist_ok=True)

    rows = [recall_row(r, k) for r in recs for k in cfg["k_sweep"]]
    df = pd.DataFrame(rows)
    df.to_csv(TABLES / "recall_per_scenario.csv", index=False)

    def agg(sub: pd.DataFrame, label: str) -> list[dict]:
        out = []
        for k, g in sub.groupby("k", sort=False):
            v = g["strict"].to_numpy(dtype=float)
            lo, hi = boot_ci(v, n_boot, rng)
            out.append({"subset": label, "k": k, "n": len(g), "strict_recall": v.mean(), "strict_ci_low": lo, "strict_ci_high": hi,
                        "fractional_recall": g["fractional"].mean(), "mean_pool_size": g["pool_size"].mean(),
                        "mean_pool_frac_of_history": g["pool_frac_of_history"].mean(), "n_cap_binds": int(g["cap_binds"].sum())})
        return out

    order = [k_label(k) for k in cfg["k_sweep"]]
    by_k = pd.DataFrame(agg(df, "all_145") + agg(df[df.family != "new_root"], "excl_new_root") + agg(df[df.family.isin(long_fams)], "long_families")
                        + agg(df[df.cap_binds == 1], "cap_binds_only") + agg(df[df.k_feasible == 1], "feasible_k_ge_closure"))
    by_k["k"] = pd.Categorical(by_k["k"], order, ordered=True)
    by_k = by_k.sort_values(["subset", "k"]).round(4)
    by_k.to_csv(TABLES / "recall_by_k.csv", index=False)

    fam = df.groupby(["family", "k"], sort=False).agg(n=("strict", "size"), strict_recall=("strict", "mean"), fractional_recall=("fractional", "mean"),
                                                        mean_pool_size=("pool_size", "mean"), n_cap_binds=("cap_binds", "sum")).reset_index()
    fam["k"] = pd.Categorical(fam["k"], order, ordered=True)
    fam = fam.sort_values(["family", "k"]).round(4)
    fam.to_csv(TABLES / "recall_by_family.csv", index=False)
    fam_pivot = df.pivot_table(index="family", columns="k", values="strict", aggfunc="mean")[order].round(3)
    fam_pivot.to_csv(TABLES / "recall_by_family_pivot.csv")

    ct = df[df.family == "compound_turn"].groupby(["variant", "k"], sort=False).agg(n=("strict", "size"), strict_recall=("strict", "mean"), fractional_recall=("fractional", "mean")).reset_index()
    ct.to_csv(TABLES / "recall_variant.csv", index=False)

    # per-source ablation: drop one source, re-rank, recompute
    abl = []
    for src in SOURCES:
        for k in cfg["k_sweep"]:
            r = [recall_row(x, k, {src}) for x in recs]
            base = df[df.k == k_label(k)]["strict"].mean()
            abl.append({"dropped_source": src, "k": k_label(k), "strict_recall": np.mean([x["strict"] for x in r]),
                        "delta_vs_full": np.mean([x["strict"] for x in r]) - base,
                        "fractional_recall": np.mean([x["fractional"] for x in r])})
    abl = pd.DataFrame(abl).round(4)
    abl.to_csv(TABLES / "recall_ablation.csv", index=False)

    # which sources find the gold turns (uncapped): attribution and sole-source counts
    attr = {s: 0 for s in SOURCES}; sole = {s: 0 for s in SOURCES}; n_gold = 0; n_missed_union = 0
    for r in recs:
        byt = {p["turn_id"]: p for p in r["pool"]}
        for g in r["gold_closure"]:
            n_gold += 1
            if g not in byt:
                n_missed_union += 1; continue
            srcs = byt[g]["sources"]
            for s_ in srcs: attr[s_] += 1
            if len(srcs) == 1: sole[srcs[0]] += 1
    attribution = pd.DataFrame([{"source": s, "gold_turns_found": attr[s], "gold_turns_found_only_by_this_source": sole[s],
                                 "share_of_gold_turns": attr[s] / n_gold} for s in SOURCES]).round(4)
    attribution.to_csv(TABLES / "recall_source_attribution.csv", index=False)

    misses = df[(df.strict == 0)].sort_values(["k", "family", "scenario_id"])
    misses.to_csv(TABLES / "recall_misses.csv", index=False)

    pk = str(cfg["primary_k"])
    head = by_k[(by_k.subset == "all_145") & (by_k.k == pk)].iloc[0]
    summary = {
        "primary_k": cfg["primary_k"],
        "strict_recall_at_primary_k_all": float(head.strict_recall), "ci": [float(head.strict_ci_low), float(head.strict_ci_high)],
        "fractional_recall_at_primary_k_all": float(head.fractional_recall),
        "strict_recall_at_primary_k_excl_new_root": float(by_k[(by_k.subset == "excl_new_root") & (by_k.k == pk)].strict_recall.iloc[0]),
        "strict_recall_at_primary_k_long_families": float(by_k[(by_k.subset == "long_families") & (by_k.k == pk)].strict_recall.iloc[0]),
        "strict_recall_at_5_all": float(by_k[(by_k.subset == "all_145") & (by_k.k == "5")].strict_recall.iloc[0]),
        "strict_recall_at_5_feasible_only": float(by_k[(by_k.subset == "feasible_k_ge_closure") & (by_k.k == "5")].strict_recall.iloc[0]),
        "n_feasible_at_5": int(by_k[(by_k.subset == "feasible_k_ge_closure") & (by_k.k == "5")].n.iloc[0]),
        "strict_recall_uncapped_all": float(by_k[(by_k.subset == "all_145") & (by_k.k == "uncapped")].strict_recall.iloc[0]),
        "n_cap_binds_at_primary_k": int(head.n_cap_binds),
        "gold_turns_total": n_gold, "gold_turns_missed_by_union": n_missed_union,
        "threshold": man["f05_decision_thresholds"]["min_candidate_recall_at_k"],
        "passes_recall_gate": bool(head.strict_recall >= man["f05_decision_thresholds"]["min_candidate_recall_at_k"]),
    }
    (TABLES / "recall_summary.json").write_text(json.dumps(summary, indent=2))

    pd.set_option("display.width", 220)
    print("== strict / fractional Candidate Recall@k ==")
    print(by_k[["subset", "k", "n", "strict_recall", "strict_ci_low", "strict_ci_high", "fractional_recall", "mean_pool_size", "mean_pool_frac_of_history", "n_cap_binds"]].to_string(index=False))
    print("\n== strict recall by family ==")
    print(fam_pivot.to_string())
    print("\n== compound_turn by variant ==")
    print(ct.to_string(index=False))
    print("\n== ablation (strict recall with one source dropped) ==")
    print(abl.pivot(index="dropped_source", columns="k", values="strict_recall")[order].round(3).to_string())
    print("\n== source attribution over gold turns (uncapped) ==")
    print(attribution.to_string(index=False))
    print("\n== headline ==")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
