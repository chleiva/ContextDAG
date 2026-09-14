"""Judge calibration (handoff §1.3, plan §4.3).

1. Draw a stratified sample of N F0 instances (family-proportional, models 50/50, methods
   spread) that already carry an Opus 4.6 verdict in F0's scores.jsonl (the reference; no new
   Opus calls).
2. Judge each sampled instance with every candidate judge (resumable, keyed by key|judge).
3. Compare each candidate to Opus: item-level Cohen's kappa (pooled, per family, per model),
   raw agreement, per-instance |Δ checklist score|, leakage kappa, method-ranking preservation
   with the tie band, cost per call. Apply the frozen adoption bar; recommend the cheapest passer.

Usage: python src/calibrate_judge.py --sample      write results/raw/calibration_sample.json
       python src/calibrate_judge.py --judge       run candidate judges (resumable)
       python src/calibrate_judge.py --analyze     tables + results/tables/judge_adopted.json
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, f0_answers, f0_scores, load_manifest, load_scenarios, method_label  # noqa: E402
from f05_cost import BudgetExceeded, ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

SAMPLE = ROOT / "results" / "raw" / "calibration_sample.json"
CAL_SCORES = ROOT / "results" / "scored" / "calibration_scores.jsonl"
TABLES = ROOT / "results" / "tables"


def draw_sample(man: dict) -> list[str]:
    rng = np.random.default_rng(man["run"]["seed"])
    cal = man["calibration"]
    n_target = cal["n_instances"]
    methods = set(cal["methods"])
    scores = f0_scores()
    answers = f0_answers()
    eligible = [r for k, r in answers.items() if method_label(r["method"], r["budget"]) in methods and k in scores
                and not (isinstance(scores[k]["checklist_score"], float) and np.isnan(scores[k]["checklist_score"]))]
    by_fam: dict[str, list[dict]] = defaultdict(list)
    for r in eligible:
        by_fam[r["family"]].append(r)
    n_scen = {f: len({r["scenario_id"] for r in rs}) for f, rs in by_fam.items()}
    total = sum(n_scen.values())
    quota = {f: max(2, round(n_target * n / total)) for f, n in n_scen.items()}
    # fix rounding so the total is exactly n_target
    while sum(quota.values()) != n_target:
        f = max(quota, key=lambda x: quota[x]) if sum(quota.values()) > n_target else min(quota, key=lambda x: quota[x])
        quota[f] += -1 if sum(quota.values()) > n_target else 1
    picked: list[str] = []
    for fam in sorted(by_fam):
        rs = by_fam[fam]
        idx = rng.permutation(len(rs))
        rs = [rs[i] for i in idx]
        # round-robin over (model, method) cells so both models and all methods are covered inside each family
        cells: dict[tuple, list[dict]] = defaultdict(list)
        for r in rs:
            cells[(r["model_key"], method_label(r["method"], r["budget"]))].append(r)
        keys = sorted(cells)
        rng.shuffle(keys)
        used_scen: set[str] = set()
        chosen: list[dict] = []
        while len(chosen) < quota[fam] and any(cells.values()):
            for c in keys:
                if len(chosen) >= quota[fam]:
                    break
                while cells[c]:
                    r = cells[c].pop()
                    if r["scenario_id"] in used_scen and sum(len(v) for v in cells.values()) > quota[fam] - len(chosen):
                        continue      # prefer distinct scenarios while there is slack
                    chosen.append(r); used_scen.add(r["scenario_id"]); break
        picked += [r["key"] for r in chosen]
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps({"n": len(picked), "quota": quota, "keys": picked}, indent=1))
    df = pd.DataFrame([answers[k] for k in picked])
    df["method_label"] = [method_label(m, b) for m, b in zip(df.method, df.budget)]
    print(f"sample: {len(picked)} instances, {df.scenario_id.nunique()} scenarios")
    print(df.groupby("family").size().to_string()); print(df.groupby("model_key").size().to_string()); print(df.groupby("method_label").size().to_string())
    return picked


def run_judges(man: dict, workers: int) -> None:
    keys = json.loads(SAMPLE.read_text())["keys"]
    answers, scen = f0_answers(), {s.scenario_id: s for s in load_scenarios()}
    done = {(r["key"], r["judge_model"]) for r in _read(CAL_SCORES)}
    todo = [(answers[k], j["id"]) for j in man["models"]["judge_candidates"] for k in keys if (k, j["id"]) not in done]
    print(f"{len(todo)} judge calls to make ({len(done)} already done)")
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(judge_instance, rec, scen[rec["scenario_id"]], jid, man, "calibration"): (rec["key"], jid) for rec, jid in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result(); append_jsonl(CAL_SCORES, out)
                if i % 20 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['judge_model']} {out['key'][:40]} score={out['checklist_score']:.2f} | run ${L.total - start:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"{fails} failures, run spend ${L.total - start:.3f}\n{L.report()}")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for l in path.read_text().splitlines():
        if l.strip():
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                pass
    return out


def _items(x) -> dict[str, bool]:
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except json.JSONDecodeError:
            x = ast.literal_eval(x)
    return {c["id"]: bool(c.get("satisfied", False)) for c in x if isinstance(c, dict) and "id" in c}


def _kappa(a: list, b: list) -> float:
    if len(a) < 2 or len(set(a)) < 2 and len(set(b)) < 2:
        return float("nan") if len(a) < 2 else 1.0
    try:
        return float(cohen_kappa_score(a, b))
    except Exception:  # noqa: BLE001
        return float("nan")


def analyze(man: dict) -> None:
    thr = man["f05_decision_thresholds"]
    keys = json.loads(SAMPLE.read_text())["keys"]
    ref = f0_scores(); answers = f0_answers()
    scen = {s.scenario_id: s for s in load_scenarios()}
    cand = defaultdict(dict)
    for r in _read(CAL_SCORES):
        cand[r["judge_model"]].setdefault(r["key"], r)
    TABLES.mkdir(parents=True, exist_ok=True)
    prices = {j["id"]: j for j in man["models"]["judge_candidates"]}
    rows, fam_rows, inst_rows = [], [], []
    ref_means = None
    for jid, recs in cand.items():
        a_items, b_items, a_leak, b_leak = [], [], [], []
        fam_items = defaultdict(lambda: ([], [])); mod_items = defaultdict(lambda: ([], []))
        deltas, method_pairs, usd, n_fb = [], defaultdict(list), 0.0, 0
        for k in keys:
            if k not in recs or k not in ref:
                continue
            r0, r1 = ref[k], recs[k]
            required = {c.id for c in scen[r0["scenario_id"]].answer_checklist if c.required}
            i0, i1 = _items(r0["checklist_items"]), _items(r1["checklist_items"])
            for cid in sorted(required):
                a_items.append(i0.get(cid, False)); b_items.append(i1.get(cid, False))
                fam_items[r0["family"]][0].append(i0.get(cid, False)); fam_items[r0["family"]][1].append(i1.get(cid, False))
                mod_items[r0["model_key"]][0].append(i0.get(cid, False)); mod_items[r0["model_key"]][1].append(i1.get(cid, False))
            if r0.get("distractor_leakage") is not None and r1.get("distractor_leakage") is not None:
                a_leak.append(int(r0["distractor_leakage"])); b_leak.append(int(r1["distractor_leakage"]))
            d = r1["checklist_score"] - r0["checklist_score"]
            deltas.append(d); usd += r1["usd"]; n_fb += int(r1.get("judge_prompt_variant") == "fallback")
            ml = method_label(r0["method"], r0["budget"])
            method_pairs[ml].append((r0["checklist_score"], r1["checklist_score"]))
            inst_rows.append({"judge": jid, "key": k, "family": r0["family"], "model_key": r0["model_key"], "method_label": ml,
                              "ref_score": r0["checklist_score"], "cand_score": r1["checklist_score"], "delta": d})
        n = len(deltas)
        if n == 0:
            continue
        ref_means = {m: np.mean([p[0] for p in v]) for m, v in method_pairs.items()}
        cand_means = {m: np.mean([p[1] for p in v]) for m, v in method_pairs.items()}
        order_ref = sorted(ref_means, key=lambda m: -ref_means[m])
        # ranking preserved: for every pair of methods whose reference means differ by >= tie band, the candidate keeps the order
        violations = []
        for i in range(len(order_ref)):
            for j in range(i + 1, len(order_ref)):
                m1, m2 = order_ref[i], order_ref[j]
                if ref_means[m1] - ref_means[m2] >= thr["judge_ranking_tie_band"] and cand_means[m1] < cand_means[m2]:
                    violations.append(f"{m1}>{m2} flipped")
        rho = spearmanr([ref_means[m] for m in order_ref], [cand_means[m] for m in order_ref]).correlation if len(order_ref) > 2 else float("nan")
        kappa = _kappa(a_items, b_items)
        mad = float(np.mean(np.abs(deltas)))
        passed = (kappa >= thr["judge_calibration_min_kappa"]) and (mad <= thr["judge_calibration_max_score_delta"]) and not violations
        rows.append({"judge": jid, "display": prices[jid]["display"], "n_instances": n, "n_items": len(a_items),
                     "item_kappa": kappa, "item_agreement": float(np.mean(np.array(a_items) == np.array(b_items))),
                     "mean_abs_score_delta": mad, "p90_abs_score_delta": float(np.percentile(np.abs(deltas), 90)),
                     "mean_signed_delta": float(np.mean(deltas)), "leakage_kappa": _kappa(a_leak, b_leak), "leakage_agreement": float(np.mean(np.array(a_leak) == np.array(b_leak))) if a_leak else float("nan"),
                     "ranking_spearman": float(rho), "ranking_violations": ";".join(violations) or "none",
                     "fallback_prompt_uses": n_fb, "usd_total": usd, "usd_per_call": usd / n,
                     "kappa_by_model": json.dumps({m: round(_kappa(*v), 3) for m, v in mod_items.items()}),
                     "PASS": passed})
        for fam, (a, b) in sorted(fam_items.items()):
            fam_rows.append({"judge": jid, "family": fam, "n_items": len(a), "item_kappa": _kappa(a, b), "item_agreement": float(np.mean(np.array(a) == np.array(b)))})
        for m in order_ref:
            fam_rows.append({"judge": jid, "family": f"[method] {m}", "n_items": len(method_pairs[m]), "item_kappa": float("nan"),
                             "item_agreement": float("nan"), "ref_mean": ref_means[m], "cand_mean": cand_means[m]})
    summ = pd.DataFrame(rows).round(4)
    summ.to_csv(TABLES / "calibration_summary.csv", index=False)
    pd.DataFrame(fam_rows).round(4).to_csv(TABLES / "calibration_by_family.csv", index=False)
    pd.DataFrame(inst_rows).round(4).to_csv(TABLES / "calibration_per_instance.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("== calibration vs Opus 4.6 (reference) ==")
    print(summ.drop(columns=["kappa_by_model"]).to_string(index=False))
    print("\nkappa by response model:"); print(summ[["display", "kappa_by_model"]].to_string(index=False))
    fam_df = pd.DataFrame(fam_rows)
    print("\n== item kappa by family ==")
    print(fam_df[~fam_df.family.str.startswith("[method]")].pivot(index="family", columns="judge", values="item_kappa").round(3).to_string())
    print("\n== method means (reference vs candidate) on the subsample ==")
    print(fam_df[fam_df.family.str.startswith("[method]")].pivot(index="family", columns="judge", values="cand_mean").round(3).assign(ref=lambda d: [ref_means[m.replace('[method] ', '')] for m in d.index]).round(3).to_string())
    passers = summ[summ.PASS]
    adopted = None
    if len(passers):
        # cheapest passer, unless another passer's kappa is clearly higher (>= 0.10) at < 2x the cost
        p = passers.sort_values("usd_per_call")
        adopted = p.iloc[0]
        for _, alt in p.iloc[1:].iterrows():
            if alt.item_kappa - adopted.item_kappa >= 0.10 and alt.usd_per_call < 2 * adopted.usd_per_call:
                adopted = alt
        out = {"adopted_judge": adopted.judge, "display": adopted.display, "item_kappa": float(adopted.item_kappa),
               "mean_abs_score_delta": float(adopted.mean_abs_score_delta), "ranking_violations": adopted.ranking_violations,
               "usd_per_call": float(adopted.usd_per_call), "passers": passers.judge.tolist(), "rule": "cheapest passer unless kappa +0.10 at <2x cost"}
        print(f"\nADOPT: {adopted.display} ({adopted.judge}) kappa={adopted.item_kappa:.3f} |Δ|={adopted.mean_abs_score_delta:.3f} ${adopted.usd_per_call:.4f}/call")
    else:
        out = {"adopted_judge": None, "passers": [], "note": "no candidate passed; next fallback is mistral.mistral-large-3-675b-instruct"}
        print("\nNO CANDIDATE PASSED the adoption bar")
    (TABLES / "judge_adopted.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true"); ap.add_argument("--judge", action="store_true"); ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    man = load_manifest()
    if args.sample:
        draw_sample(man)
    if args.judge:
        run_judges(man, args.workers)
    if args.analyze:
        analyze(man)
