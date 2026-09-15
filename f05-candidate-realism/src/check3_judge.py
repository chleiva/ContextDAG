"""Check 3 replication judge (handoff §3.3, §3.4): score with Llama 4 Maverick every instance the
check-3 tables need that it has not judged yet.

Sources: F0 answers (semantic_retrieval@{1024,2048}, rolling_summary@{1024,2048}, sliding_window@2048
for response_a/b), F0.5 answers (candidate_oracle@15 for a/b, every response_c row incl. the new
check-3 baselines). Existing Llama verdicts from the calibration set are reused, not re-bought.
Copied answers inherit the verdict of their source. Output: results/scored/check3_llama_scores.jsonl.
Run with F05_LEDGER=check3.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get("F05_LEDGER") != "check3":
    print("Refusing: set F05_LEDGER=check3", file=sys.stderr); sys.exit(2)
from f0_bridge import ROOT, f0_answers, load_manifest, load_scenarios, method_label, read_jsonl  # noqa: E402
from f05_cost import BudgetExceeded, ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

OUT = ROOT / "results" / "scored" / "check3_llama_scores.jsonl"
CAL = ROOT / "results" / "scored" / "calibration_scores.jsonl"
F05_ANS = ROOT / "results" / "raw" / "answers.jsonl"

F0_METHODS = {"semantic_retrieval@1024", "semantic_retrieval@2048", "rolling_summary@1024", "rolling_summary@2048", "sliding_window@2048"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    man = load_manifest()
    jid = man["check3"]["replication_judge"]
    scen = {s.scenario_id: s for s in load_scenarios()}
    have = {r["key"]: r for r in read_jsonl(OUT)}
    # reuse calibration-set Llama verdicts
    reused = 0
    for r in read_jsonl(CAL):
        if r["judge_model"] == jid and r["key"] not in have:
            append_jsonl(OUT, r); have[r["key"]] = r; reused += 1
    f0 = f0_answers()
    own = read_jsonl(F05_ANS)
    todo = [r for k, r in f0.items() if r["model_key"] in ("response_a", "response_b") and method_label(r["method"], r["budget"]) in F0_METHODS and k not in have]
    todo += [r for r in own if r["key"] not in have and "response" in r and (r["model_key"] == "response_c" or (r["method"] == "candidate_oracle" and r["budget"] == 15))]
    # copies inherit
    copies = [r for r in todo if r.get("copied_from")]
    todo = [r for r in todo if not r.get("copied_from")]
    print(f"reused {reused} calibration verdicts; {len(todo)} to judge; {len(copies)} copies to resolve after")
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_instance, r, scen[r["scenario_id"]], jid, man, "check3-judge"): r["key"] for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result(); append_jsonl(OUT, out); have[out["key"]] = out
                if i % 50 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key'][:55]} score={out['checklist_score']:.2f} | run ${L.total - start:.3f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:160]}", flush=True)
    n_copy = 0
    for r in copies:
        src = have.get(r["copied_from"])
        if src:
            out = dict(src); out.update({"key": r["key"], "method": r["method"], "budget": r["budget"], "copied_from": r["copied_from"], "usd": 0.0})
            append_jsonl(OUT, out); have[r["key"]] = out; n_copy += 1
    print(f"{fails} failures, {n_copy} copies resolved, run spend ${L.total - start:.3f}\n{L.report()}")


if __name__ == "__main__":
    main()
