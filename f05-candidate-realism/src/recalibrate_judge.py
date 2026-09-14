"""Judge recalibration extension (Judge_Recalibration_Exten.md, 14 Sep 2026).

Reuses F0.5's 160-instance calibration sample and Opus 4.6 reference verdicts (no new Opus calls).
1. `--judge`   score the same 160 instances with the new candidates in manifest judge_recalibration
               (resumable; rows appended to results/scored/calibration_scores.jsonl like the originals).
2. `--analyze` apply judge_adoption_bar_v2 to ALL non-Opus candidates: item kappa >= 0.6, method
               ranking preserved (tie band), and |candidate contrast - Opus contrast| <= 0.02 on every
               one of dag-full, dag-tree, dag-sliding, dag-semantic. Cheapest passer is selected.

Run with F05_LEDGER=recalibration so spend goes to the extension's own $5-capped ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get("F05_LEDGER") != "recalibration":
    print("NOTE: F05_LEDGER=recalibration not set; spend would go to the F0.5 ledger. Refusing.", file=sys.stderr)
    sys.exit(2)
from calibrate_judge import CAL_SCORES, SAMPLE, TABLES, _items, _kappa, _read  # noqa: E402
from f0_bridge import f0_answers, f0_scores, load_manifest, load_scenarios, method_label  # noqa: E402
from f05_cost import BudgetExceeded, ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

CONTRASTS = {"dag_minus_full": ("oracle_dag", "full_history"), "dag_minus_tree": ("oracle_dag", "oracle_tree"),
             "dag_minus_sliding": ("oracle_dag", "sliding_window@1024"), "dag_minus_semantic": ("oracle_dag", "semantic_retrieval@1024")}


def run_judges(man: dict, workers: int) -> None:
    rc = man["judge_recalibration"]
    keys = json.loads(SAMPLE.read_text())["keys"]
    answers, scen = f0_answers(), {s.scenario_id: s for s in load_scenarios()}
    done = {(r["key"], r["judge_model"]) for r in _read(CAL_SCORES)}
    todo = [(answers[k], c) for c in rc["new_candidates"] for k in keys if (k, c["id"]) not in done]
    print(f"{len(todo)} judge calls to make ({len(done)} rows already present)")
    L = ledger(); start = L.total; fails = 0

    def one(rec, c):
        # per-candidate temperature: None means "omit" (GPT-5 mini/nano accept only the default)
        m = dict(man); m["models"] = dict(man["models"]); m["models"]["judge_settings"] = dict(man["models"]["judge_settings"])
        m["models"]["judge_settings"]["temperature"] = c.get("temperature", 0.0)
        return judge_instance(rec, scen[rec["scenario_id"]], c["id"], m, "recalibration")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, rec, c): (rec["key"], c["id"]) for rec, c in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result(); append_jsonl(CAL_SCORES, out)
                if i % 40 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['judge_model']} {out['key'][:40]} score={out['checklist_score']:.2f} | run ${L.total - start:.3f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"{fails} failures, run spend ${L.total - start:.3f}\n{L.report()}")


def analyze(man: dict) -> None:
    rc = man["judge_recalibration"]
    bar = rc["judge_adoption_bar_v2"]
    keys = json.loads(SAMPLE.read_text())["keys"]
    ref, answers = f0_scores(), f0_answers()
    scen = {s.scenario_id: s for s in load_scenarios()}
    prices = man["pricing_usd_per_1m_tokens"]
    disp = {c["id"]: c["display"] for c in man["models"]["judge_candidates"]} | {c["id"]: c["display"] for c in rc["new_candidates"]}
    cand: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in _read(CAL_SCORES):
        cand[r["judge_model"]].setdefault(r["key"], r)
    # reference method means and contrasts on the sample
    def method_means(getter) -> dict[str, float]:
        by = defaultdict(list)
        for k in keys:
            v = getter(k)
            if v is not None:
                by[method_label(answers[k]["method"], answers[k]["budget"])].append(v)
        return {m: float(np.mean(v)) for m, v in by.items()}
    ref_means = method_means(lambda k: ref[k]["checklist_score"])
    ref_c = {name: ref_means[a] - ref_means[b] for name, (a, b) in CONTRASTS.items()}
    order_ref = sorted(ref_means, key=lambda m: -ref_means[m])
    rows = []
    for jid, recs in cand.items():
        n = sum(1 for k in keys if k in recs)
        if n == 0:
            continue
        a_items, b_items, deltas, usd = [], [], [], 0.0
        for k in keys:
            if k not in recs:
                continue
            required = {c.id for c in scen[answers[k]["scenario_id"]].answer_checklist if c.required}
            i0, i1 = _items(ref[k]["checklist_items"]), _items(recs[k]["checklist_items"])
            for cid in sorted(required):
                a_items.append(i0.get(cid, False)); b_items.append(i1.get(cid, False))
            deltas.append(recs[k]["checklist_score"] - ref[k]["checklist_score"]); usd += recs[k]["usd"]
        c_means = method_means(lambda k: recs[k]["checklist_score"] if k in recs else None)
        c_c = {name: c_means[a] - c_means[b] for name, (a, b) in CONTRASTS.items()}
        errs = {name: c_c[name] - ref_c[name] for name in CONTRASTS}
        violations = []
        for i in range(len(order_ref)):
            for j in range(i + 1, len(order_ref)):
                m1, m2 = order_ref[i], order_ref[j]
                if ref_means[m1] - ref_means[m2] >= bar["ranking_tie_band"] and c_means[m1] < c_means[m2]:
                    violations.append(f"{m1}>{m2} flipped")
        kappa = _kappa(a_items, b_items)
        # sampling noise of each contrast error: paired bootstrap over the sample's instances
        rng = np.random.default_rng(man["run"]["seed"])
        ks = [k for k in keys if k in recs]
        ml = np.array([method_label(answers[k]["method"], answers[k]["budget"]) for k in ks])
        rv = np.array([ref[k]["checklist_score"] for k in ks]); cv = np.array([recs[k]["checklist_score"] for k in ks])
        boots = {name: [] for name in CONTRASTS}
        for _ in range(2000):
            idx = rng.integers(0, len(ks), len(ks))
            m_r, m_c = {}, {}
            for m in set(ml):
                sel = idx[ml[idx] == m]
                if len(sel) == 0:
                    break
                m_r[m], m_c[m] = rv[sel].mean(), cv[sel].mean()
            if len(m_r) < len(set(ml)):
                continue
            for name, (a, b) in CONTRASTS.items():
                boots[name].append((m_c[a] - m_c[b]) - (m_r[a] - m_r[b]))
        err_ci = {name: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))) for name, v in boots.items()}
        err_se = {name: float(np.std(v)) for name, v in boots.items()}
        rank_ok = not violations
        contrast_ok = all(abs(e) <= bar["contrast_error_max"] for e in errs.values())
        passed = kappa >= bar["item_kappa_min"] and rank_ok and contrast_ok
        rows.append({"judge": jid, "display": disp.get(jid, jid), "n": n, "n_items": len(a_items), "item_kappa": kappa,
                     "item_agreement": float(np.mean(np.array(a_items) == np.array(b_items))),
                     "ranking_preserved": rank_ok, "ranking_violations": ";".join(violations) or "none",
                     "ranking_spearman": float(spearmanr([ref_means[m] for m in order_ref], [c_means[m] for m in order_ref]).correlation),
                     **{f"err_{name}": errs[name] for name in CONTRASTS}, "max_abs_contrast_err": max(abs(e) for e in errs.values()),
                     **{f"se_{name}": err_se[name] for name in CONTRASTS},
                     "mean_err_se": float(np.mean(list(err_se.values()))),
                     "n_contrast_errs_ci_excludes_zero": sum(1 for name in CONTRASTS if not (err_ci[name][0] <= 0 <= err_ci[name][1])),
                     **{f"cand_{name}": c_c[name] for name in CONTRASTS},
                     "mean_abs_score_delta_v1": float(np.mean(np.abs(deltas))), "mean_signed_delta": float(np.mean(deltas)),
                     "usd_per_call": usd / n, "PASS_v2": passed,
                     "fallback_prompt_uses": sum(1 for k in keys if k in recs and recs[k].get("judge_prompt_variant") == "fallback"),
                     "routes": ";".join(sorted({recs[k].get("judge_route", "") for k in keys if k in recs}))})
    df = pd.DataFrame(rows).sort_values("usd_per_call")
    df.round(4).to_csv(TABLES / "recalibration_summary.csv", index=False)
    mm = pd.DataFrame({"Opus 4.6 (reference)": ref_means} | {disp.get(j, j): method_means(lambda k, r=cand[j]: r[k]["checklist_score"] if k in r else None) for j in cand}).loc[order_ref]
    mm.round(4).to_csv(TABLES / "recalibration_method_means.csv")
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    print("Opus reference contrasts:", {k: round(v, 4) for k, v in ref_c.items()})
    print("\n== bar v2 ==")
    print(df[["display", "n", "item_kappa", "ranking_preserved", "err_dag_minus_full", "err_dag_minus_tree", "err_dag_minus_sliding", "err_dag_minus_semantic", "max_abs_contrast_err", "mean_abs_score_delta_v1", "usd_per_call", "PASS_v2"]].round(4).to_string(index=False))
    print("\n== method means on the sample ==\n" + mm.round(3).to_string())
    passers = df[df.PASS_v2]
    out = {"bar": bar, "reference_contrasts": ref_c, "passers": passers.judge.tolist(),
           "standing_judge": (passers.iloc[0].judge if len(passers) else None),
           "standing_judge_display": (passers.iloc[0].display if len(passers) else None), "rule": "cheapest passer (usd_per_call)"}
    (TABLES / "judge_recalibration_decision.json").write_text(json.dumps(out, indent=2, default=float))
    print("\nSTANDING JUDGE:", out["standing_judge_display"] or "NONE PASSED", "| passers:", out["passers"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true"); ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    man = load_manifest()
    if args.judge:
        run_judges(man, args.workers)
    if args.analyze:
        analyze(man)
