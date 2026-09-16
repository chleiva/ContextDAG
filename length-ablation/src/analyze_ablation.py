"""Length-ablation analysis (handoff §4, §5). Assembles the long table from: this phase's answers +
Llama verdicts (30/60 full_history, Stage-2 retrieval) and the reused base arms (F0 full_history and
oracle_dag answers for a/b, F0.5 for c; Llama verdicts from check 3). Cluster bootstrap over target
ids, 10,000 resamples, one pinned seed per comparison. No LLM calls."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import la  # noqa: E402,F401
from la import RAW, SCORED, TABLES, load_manifest, read_jsonl  # noqa: E402

RETRACT = re.compile(r"fabricat|I (?:have )?(?:been )?invent|made up|I need to (?:stop|be transparent|be honest|correct)|I (?:don't|do not) (?:actually )?have (?:any )?(?:record|information|access)|cannot verify|not a real person|I should not continue|there is no (?:record|prior)", re.I)


def rng_for(seed, *parts):
    return np.random.default_rng(int.from_bytes(hashlib.sha256("|".join([str(seed), *parts]).encode()).digest()[:8], "little"))


def boot(d, n, rng):
    idx = rng.integers(0, len(d), size=(n, len(d))); m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def load(man: dict) -> pd.DataFrame:
    rows = []
    for r in read_jsonl(RAW / "answers.jsonl"):
        rows.append(r)
    own_scores = {}
    for r in read_jsonl(SCORED / "scores.jsonl"):
        own_scores.setdefault(r["key"], r)
    # reused base arms
    targets = {r["target"] for r in rows} if rows else set()
    if not targets:
        from run_ablation import targets_and_sets
        targets = {t.scenario_id for t in targets_and_sets()[0]}
    f0 = {}
    for r in read_jsonl(la.REPO / "f0-oracle-feasibility" / "results" / "raw" / "answers.jsonl"):
        f0[r["key"]] = r
    for r in read_jsonl(la.REPO / "f05-candidate-realism" / "results" / "raw" / "answers.jsonl"):
        f0.setdefault(r["key"], r)
    llama = {}
    for r in read_jsonl(la.REPO / "f05-candidate-realism" / "results" / "scored" / "check3_llama_scores.jsonl"):
        llama.setdefault(r["key"], r)
    ids = {man["models"][k]["id"]: k for k in ("response_a", "response_b", "response_c")}
    for tid in targets:
        for mid, mk in ids.items():
            for meth in ("full_history", "oracle_dag"):
                k = f"{tid}|{meth}|-|{mid}"
                if k in f0:
                    r = dict(f0[k]); r.update({"target": tid, "length": "base", "method_label": meth, "model_key": mk, "reused": True}); rows.append(r)
                    if k in llama:
                        own_scores.setdefault(k, llama[k])
    df = pd.DataFrame(rows).drop_duplicates("key", keep="first")
    sc = pd.DataFrame(list(own_scores.values()))[["key", "checklist_score", "distractor_leakage"]] if own_scores else pd.DataFrame(columns=["key"])
    df = df.merge(sc, on="key", how="left")
    df["retraction"] = df.response.fillna("").str[:600].map(lambda t: bool(RETRACT.search(t))).astype(int)
    df["length"] = df["length"].astype(str)
    return df


def paired(df, mk, a, b, seed, n):
    """a, b are (method_label, length) cells; paired over target ids within model mk (or pooled by within-target mean)."""
    sub = df if mk is None else df[df.model_key == mk]
    pa = sub[(sub.method_label == a[0]) & (sub.length == str(a[1]))].groupby("target")[["checklist_score", "context_tokens", "distractor_leakage"]].mean()
    pb = sub[(sub.method_label == b[0]) & (sub.length == str(b[1]))].groupby("target")[["checklist_score", "context_tokens", "distractor_leakage"]].mean()
    common = pa.index.intersection(pb.index); pa, pb = pa.loc[common], pb.loc[common]
    ok = ~(pa.checklist_score.isna() | pb.checklist_score.isna())
    if ok.sum() < 5:
        return None
    d = (pa.checklist_score - pb.checklist_score)[ok].to_numpy(dtype=float)
    mean, lo, hi = boot(d, n, rng_for(seed, mk or "pooled", f"{a[0]}@{a[1]}", f"{b[0]}@{b[1]}"))
    return {"model": mk or "pooled", "a": f"{a[0]}@{a[1]}", "b": f"{b[0]}@{b[1]}", "n": int(ok.sum()), "q_diff": mean, "q_ci_low": lo, "q_ci_high": hi,
            "se": float(d.std(ddof=1) / np.sqrt(len(d))), "tok_a": float(pa.context_tokens[ok].mean()), "tok_b": float(pb.context_tokens[ok].mean())}


def main() -> None:
    man = load_manifest(); seed = man["run"]["seed"]; n = 10000
    TABLES.mkdir(parents=True, exist_ok=True)
    df = load(man)
    df.drop(columns=[c for c in ("prompt", "system_prompt", "response") if c in df.columns]).to_csv(TABLES / "instances.csv", index=False)
    print(f"{len(df)} instances, {df.checklist_score.notna().sum()} scored; cells: {sorted(set(zip(df.method_label, df.length)))}")
    models = ["response_a", "response_b", "response_c"]
    rows = []
    for mk in models + [None]:
        for a, b in [(("full_history", "base"), ("full_history", 60)), (("full_history", "base"), ("full_history", 30)), (("full_history", 30), ("full_history", 60)),
                     (("oracle_dag", "base"), ("full_history", "base")), (("oracle_dag", "base"), ("full_history", 30)), (("oracle_dag", "base"), ("full_history", 60)),
                     (("oracle_dag", "base"), ("semantic_retrieval@matched", "base")), (("oracle_dag", "base"), ("semantic_retrieval@matched", 30)), (("oracle_dag", "base"), ("semantic_retrieval@matched", 60)),
                     (("semantic_retrieval@matched", "base"), ("semantic_retrieval@matched", 60))]:
            r = paired(df, mk, a, b, seed, n)
            if r: rows.append(r)
    comp = pd.DataFrame(rows).round(4); comp.to_csv(TABLES / "comparisons.csv", index=False)
    # per-cell diagnostics: checklist, leakage, retraction, tokens, recall
    cells = df.groupby(["model_key", "method_label", "length"]).agg(n=("key", "size"), n_scored=("checklist_score", "count"), checklist=("checklist_score", "mean"),
                                                                    leakage=("distractor_leakage", "mean"), retraction=("retraction", "mean"), context_tokens=("context_tokens", "mean"),
                                                                    context_recall=("context_recall", "mean"), context_precision=("context_precision", "mean")).reset_index().round(4)
    cells.to_csv(TABLES / "cells.csv", index=False)
    # validity: leakage must rise with length on full_history (per model and pooled)
    lk = {}
    for mk in models + ["pooled"]:
        sub = df if mk == "pooled" else df[df.model_key == mk]
        fh = sub[sub.method_label == "full_history"].groupby("length").distractor_leakage.mean()
        lk[mk] = {k: (float(fh[k]) if k in fh else None) for k in ("base", "30", "60")}
    valid = all(lk[m]["60"] is not None and lk[m]["base"] is not None and lk[m]["60"] > lk[m]["base"] for m in ["pooled"])
    # interpretation, mechanical, on the primary (pooled and per model)
    def read(r):
        if r is None: return "n/a"
        if r["q_diff"] >= 0.05 and r["q_ci_low"] > 0: return "AMPLIFIES"
        if 0.02 <= r["q_diff"] < 0.05: return "DIRECTIONAL"
        if r["q_diff"] >= 0.05: return "DIRECTIONAL (>= 5 pp but CI includes zero)"
        return "CLOSED (< +2 pp or negative)"
    prim = {m: (comp[(comp.model == m) & (comp.a == "full_history@base") & (comp.b == "full_history@60")].iloc[0].to_dict() if len(comp[(comp.model == m) & (comp.a == "full_history@base") & (comp.b == "full_history@60")]) else None) for m in models + ["pooled"]}
    out = {"validity_leakage_rises_with_length_pooled": bool(valid), "leakage_by_length": lk, "primary": prim, "reading": {m: read(prim[m]) for m in prim},
           "stage2_present": bool((df.method_label == "semantic_retrieval@matched").any())}
    (TABLES / "decision.json").write_text(json.dumps(out, indent=2, default=float))
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("\n== cells ==\n" + cells.to_string(index=False)); print("\n== comparisons ==\n" + comp.to_string(index=False))
    print("\n== leakage by length ==", json.dumps(lk)); print("validity (pooled leakage rises base->60):", valid)
    print("== reading ==", json.dumps(out["reading"]))


if __name__ == "__main__":
    main()
