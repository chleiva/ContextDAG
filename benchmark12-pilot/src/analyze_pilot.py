"""Benchmark 1.2 pilot analysis: the §5 gate applied mechanically, plus everything §5 says to
report. Cluster bootstrap over scenario ids, 10,000 resamples, with a pinned seed PER COMPARISON
derived from (run seed, model, a, b, judge) so every table is byte-identical regardless of the
order comparisons are evaluated. No LLM calls.

Outputs in results/tables: comparisons.csv, arms.csv, validation.csv, gate.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot  # noqa: E402,F401
from pilot import META, RAW, SCORED, TABLES, load_manifest, load_scenarios, read_jsonl  # noqa: E402

ARMS = ["full_history", "oracle_dag", "semantic_retrieval@matched", "semantic_retrieval@1024"]


def rng_for(seed: int, *parts: str) -> np.random.Generator:
    h = hashlib.sha256(("|".join([str(seed), *parts])).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


def boot(d: np.ndarray, n: int, rng) -> tuple[float, float, float]:
    idx = rng.integers(0, len(d), size=(n, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def load() -> pd.DataFrame:
    a = pd.DataFrame(read_jsonl(RAW / "answers.jsonl")).drop_duplicates("key", keep="last")
    sc = {}
    for r in read_jsonl(SCORED / "scores.jsonl"):
        sc.setdefault(r["key"], r)
    s = pd.DataFrame(list(sc.values())) if sc else pd.DataFrame(columns=["key"])
    keep = [c for c in ("key", "checklist_score", "all_required_satisfied", "distractor_leakage", "judge_route", "judge_prompt_variant") if c in s.columns]
    return a.merge(s[keep], on="key", how="left")


def paired(df: pd.DataFrame, mk, a: str, b: str, seed: int, n: int, pooled: bool = False) -> dict | None:
    sub = df if mk is None else df[df.model_key == mk]
    if pooled:
        models = sorted(set(sub[(sub.method_label == a) & sub.checklist_score.notna()].model_key) & set(sub[(sub.method_label == b) & sub.checklist_score.notna()].model_key))
        sub = sub[sub.model_key.isin(models)]
        pa = sub[sub.method_label == a].groupby("scenario_id")[["checklist_score", "context_tokens"]].mean()
        pb = sub[sub.method_label == b].groupby("scenario_id")[["checklist_score", "context_tokens"]].mean()
    else:
        pa = sub[sub.method_label == a].set_index("scenario_id")[["checklist_score", "context_tokens"]]
        pb = sub[sub.method_label == b].set_index("scenario_id")[["checklist_score", "context_tokens"]]
    common = pa.index.intersection(pb.index); pa, pb = pa.loc[common], pb.loc[common]
    ok = ~(pa.checklist_score.isna() | pb.checklist_score.isna())
    if ok.sum() < 5:
        return None
    dq = (pa.checklist_score - pb.checklist_score)[ok].to_numpy(dtype=float)
    ta, tb = pa.context_tokens[ok].to_numpy(dtype=float), pb.context_tokens[ok].to_numpy(dtype=float)
    rng = rng_for(seed, mk or "pooled", a, b)
    mean, lo, hi = boot(dq, n, rng)
    idx = rng.integers(0, len(ta), size=(n, len(ta))); br = ta[idx].mean(axis=1) / tb[idx].mean(axis=1)
    return {"model": mk or "pooled", "a": a, "b": b, "n": int(ok.sum()), "q_diff": mean, "q_ci_low": lo, "q_ci_high": hi,
            "se": float(dq.std(ddof=1) / np.sqrt(len(dq))), "tok_ratio": float(ta.mean() / tb.mean()),
            "tok_ratio_ci_low": float(np.percentile(br, 2.5)), "tok_ratio_ci_high": float(np.percentile(br, 97.5)),
            "pooled_models": ",".join(models) if pooled else ""}


def main() -> None:
    man = load_manifest(); seed = man["run"]["seed"]; n_boot = 10000; gate = man["benchmark12_pilot"]; thr = gate["thresholds"]
    TABLES.mkdir(parents=True, exist_ok=True)
    df = load()
    print(f"{len(df)} answers, {df.checklist_score.notna().sum()} scored")
    models = ["response_a", "response_b", "response_c"]
    rows = []
    for mk in models:
        for a, b in [("oracle_dag", "full_history"), ("oracle_dag", "semantic_retrieval@matched"), ("oracle_dag", "semantic_retrieval@1024"),
                     ("semantic_retrieval@matched", "full_history"), ("semantic_retrieval@1024", "full_history")]:
            r = paired(df, mk, a, b, seed, n_boot)
            if r: rows.append(r)
    for a, b in [("oracle_dag", "full_history"), ("oracle_dag", "semantic_retrieval@matched")]:
        r = paired(df, None, a, b, seed, n_boot, pooled=True)
        if r: rows.append(r)
    comp = pd.DataFrame(rows).round(4)
    comp.to_csv(TABLES / "comparisons.csv", index=False)

    # per-arm table with CIs (pinned seeds)
    arm_rows = []
    for (mk, ml), g in df.groupby(["model_key", "method_label"]):
        g = g.drop_duplicates("scenario_id")
        rec = {"model": mk, "arm": ml, "n": len(g), "context_tokens": g.context_tokens.mean(), "context_precision": g.context_precision.mean(),
               "irrelevant_context_ratio": g.irrelevant_context_ratio.mean(), "context_recall": g.context_recall.mean(),
               "distractor_leakage": g.distractor_leakage.dropna().mean() if g.distractor_leakage.notna().any() else np.nan,
               "output_tokens": g.output_tokens.mean()}
        v = g.checklist_score.dropna().to_numpy(dtype=float)
        if len(v) >= 5:
            rec["checklist"], rec["q_ci_low"], rec["q_ci_high"] = boot(v, n_boot, rng_for(seed, mk, ml, "arm"))
        arm_rows.append(rec)
    arms = pd.DataFrame(arm_rows).round(4)
    full = arms[arms.arm == "full_history"].set_index("model").context_tokens
    arms["token_ratio_vs_full"] = [r.context_tokens / full[r.model] for r in arms.itertuples()]
    arms = arms.round(4); arms.to_csv(TABLES / "arms.csv", index=False)

    # validation tables (§3, §3.1): cosine gate first-attempt vs final, closure ratio, length
    metas = [json.loads(p.read_text()) for p in sorted(META.glob("*.json"))]
    attempts = read_jsonl(RAW / "cosine_gate_attempts.jsonl")
    first = {}
    for r in attempts:
        first.setdefault(r["scenario_id"], r)
    val = pd.DataFrame([{"scenario_id": m["scenario_id"], "family": m["family"], "n_history": m["n_history"], "full_history_tokens": m["full_history_tokens"],
                         "closure_ratio": m["closure_ratio"], "cosine_ratio_final": m["cosine"]["ratio"], "gate_pass_final": m["cosine"]["pass"],
                         "cosine_ratio_first_attempt": first.get(m["scenario_id"], {}).get("ratio"), "gate_pass_first_attempt": first.get(m["scenario_id"], {}).get("pass"),
                         "attempts": m.get("attempt_accepted"), "n_registry": len(m["entity_registry"]), "near_miss": m["near_miss_turn_id"]} for m in metas])
    val.to_csv(TABLES / "validation.csv", index=False)
    vfam = val.groupby("family").agg(n=("scenario_id", "size"), history=("n_history", "mean"), tokens=("full_history_tokens", "mean"), closure_ratio_median=("closure_ratio", "median"),
                                     cosine_ratio_median=("cosine_ratio_final", "median"), gate_pass_final=("gate_pass_final", "mean"),
                                     gate_pass_first=("gate_pass_first_attempt", lambda x: float(np.mean([bool(v) for v in x if v is not None])) if any(v is not None for v in x) else np.nan),
                                     attempts_mean=("attempts", "mean")).round(3)
    vfam.to_csv(TABLES / "validation_by_family.csv")

    # the gate, mechanically
    prim = {mk: comp[(comp.model == mk) & (comp.a == "oracle_dag") & (comp.b == "full_history")] for mk in models}
    est = {mk: (float(prim[mk].q_diff.iloc[0]) if len(prim[mk]) else None) for mk in models}
    n_amp = sum(1 for v in est.values() if v is not None and v >= thr["amplifies_pp"])
    n_partial_or_more = sum(1 for v in est.values() if v is not None and v >= thr["partial_low_pp"])
    n_flat = sum(1 for v in est.values() if v is not None and v < thr["partial_low_pp"])
    if n_amp >= thr["models_required"]:
        verdict = "AMPLIFIES"
    elif n_partial_or_more >= thr["models_required"]:
        verdict = "PARTIAL"
    elif n_flat >= thr["models_required"]:
        verdict = "FLAT"
    else:
        verdict = "AWKWARD"
    pooled = comp[(comp.model == "pooled") & (comp.a == "oracle_dag") & (comp.b == "full_history")]
    out = {"verdict": verdict, "point_estimates": est, "n_models_ge_5pp": n_amp, "n_models_ge_4pp": n_partial_or_more, "n_models_lt_4pp": n_flat,
           "thresholds": thr, "pooled": (pooled.iloc[0].to_dict() if len(pooled) else None),
           "per_model": {mk: (prim[mk].iloc[0].to_dict() if len(prim[mk]) else None) for mk in models},
           "cosine_gate_first_attempt_pass_rate": float(val.gate_pass_first_attempt.dropna().astype(bool).mean()) if len(val) else None,
           "cosine_gate_final_pass_rate": float(val.gate_pass_final.astype(bool).mean()) if len(val) else None,
           "closure_ratio_median": float(val.closure_ratio.median()) if len(val) else None}
    (TABLES / "gate.json").write_text(json.dumps(out, indent=2, default=float))
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("\n== validation by family ==\n" + vfam.to_string())
    print("\n== comparisons ==\n" + comp.to_string(index=False))
    print("\n== arms ==\n" + arms.to_string(index=False))
    print(f"\n== GATE: {verdict} == point estimates {json.dumps({k: (round(v, 4) if v is not None else None) for k, v in est.items()})}")


if __name__ == "__main__":
    main()
