"""Check-3 rework item 3: variance decomposition on the 432 identical-prompt pairs
(candidate_oracle@15 vs oracle_dag, same prompt, independent temperature-0 draws), Opus verdicts.

σ²_decoder = var(paired checklist difference) / 2       (two independent draws per pair)
σ²_total   = per-scenario variance of candidate_oracle@15 checklist score (the cluster bootstrap's unit)
σ²_scenario = σ²_total − σ²_decoder
Sample-size table: σ_eff(k) = sqrt(σ²_scenario + σ²_decoder / k); n = 7.84 σ_eff² / 0.026².
No LLM calls. Output: results/check3/rework_variance.json + rework_sample_size.csv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, f0_answers, f0_scores, load_manifest, read_jsonl  # noqa: E402

OUT = ROOT / "results" / "check3"


def main() -> None:
    man = load_manifest()
    rng = np.random.default_rng(man["run"]["seed"])
    f0 = f0_answers(); f05 = {r["key"]: r for r in read_jsonl(ROOT / "results" / "raw" / "answers.jsonl")}
    opus = dict(f0_scores())
    for r in read_jsonl(ROOT / "results" / "scored" / "scores.jsonl"):
        opus.setdefault(r["key"], r)
    pairs, totals = [], []
    for k, r in f05.items():
        if r["method"] != "candidate_oracle" or r["budget"] != 15 or r.get("copied_from"):
            continue
        dk = f"{r['scenario_id']}|oracle_dag|-|{r['model']}"
        d = f0.get(dk) or f05.get(dk)
        if d and r["prompt"] == d["prompt"] and k in opus and dk in opus:
            pairs.append({"model_key": r["model_key"], "scenario_id": r["scenario_id"], "diff": opus[k]["checklist_score"] - opus[dk]["checklist_score"],
                          "cand": opus[k]["checklist_score"]})
    df = pd.DataFrame(pairs)
    print(f"{len(df)} identical-prompt pairs")

    def decomp(sub: pd.DataFrame) -> dict:
        d, c = sub["diff"].to_numpy(), sub["cand"].to_numpy()
        n = len(d)
        est = lambda dd, cc: (np.var(dd, ddof=1) / 2, np.var(cc, ddof=1))  # noqa: E731
        v_dec, v_tot = est(d, c)
        bs = np.array([est(d[i], c[i]) for i in (rng.integers(0, n, n) for _ in range(5000))])
        ci = lambda col: [float(np.percentile(col, 2.5)), float(np.percentile(col, 97.5))]  # noqa: E731
        v_sc = v_tot - v_dec
        return {"n_pairs": int(n), "sigma2_decoder": float(v_dec), "sigma2_decoder_ci": ci(bs[:, 0]),
                "sigma2_total": float(v_tot), "sigma2_total_ci": ci(bs[:, 1]),
                "sigma2_scenario": float(v_sc), "sigma2_scenario_ci": ci(bs[:, 1] - bs[:, 0]),
                "decoder_share": float(v_dec / v_tot), "decoder_share_ci": ci(bs[:, 0] / bs[:, 1]),
                "identical_score_pairs": int((d == 0).sum())}

    res = {mk: decomp(df[df.model_key == mk]) for mk in sorted(df.model_key.unique())}
    res["pooled"] = decomp(df)
    rows = []
    for name, r in res.items():
        for k in (1, 2, 3, 5):
            se = np.sqrt(max(r["sigma2_scenario"], 0) + r["sigma2_decoder"] / k)
            rows.append({"arm": name, "k_samples_per_cell": k, "sigma_eff": se, "n_scenarios_for_2.6pp_80pct_power": 7.84 * se ** 2 / 0.026 ** 2})
    ss = pd.DataFrame(rows).round(4)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rework_variance.json").write_text(json.dumps(res, indent=2))
    ss.to_csv(OUT / "rework_sample_size.csv", index=False)
    pd.set_option("display.width", 200)
    print(json.dumps(res, indent=1)); print(ss.to_string(index=False))


if __name__ == "__main__":
    main()
