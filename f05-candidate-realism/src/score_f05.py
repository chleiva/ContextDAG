"""Score answers with the adopted cheap judge (handoff §5.6), same protocol as F0.

Two answer sources, both written to results/scored/scores.jsonl keyed like F0:
- F0.5's own answers (results/raw/answers.jsonl): candidate_oracle arms and the MiniMax arm.
- `--rejudge-f0`: F0's existing full_history and oracle_dag answers for response_a/b, so every
  arm in the F0.5 comparison is judged by the same model (plan §3.6).

Judge id: manifest models.judge.id if set, else results/tables/judge_adopted.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, f0_answers, load_manifest, load_scenarios, read_jsonl  # noqa: E402
from f05_cost import BudgetExceeded, ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
SCORES = ROOT / "results" / "scored" / "scores.jsonl"
ADOPTED = ROOT / "results" / "tables" / "judge_adopted.json"


def adopted_judge(man: dict) -> str:
    jid = man["models"]["judge"].get("id")
    if jid:
        return jid
    if ADOPTED.exists():
        jid = json.loads(ADOPTED.read_text()).get("adopted_judge")
    if not jid:
        raise SystemExit("no adopted judge: run calibrate_judge.py --analyze first")
    return jid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rejudge-f0", action="store_true", help="also judge F0's full_history/oracle_dag answers for response_a/b")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--models", default=None, help="comma-separated model_keys to score (default all)")
    args = ap.parse_args()
    man = load_manifest()
    jid = adopted_judge(man)
    scen = {s.scenario_id: s for s in load_scenarios()}
    scored = {r["key"]: r for r in read_jsonl(SCORES)}
    done = set(scored)
    own = [r for r in read_jsonl(ANSWERS) if r["key"] not in done and "response" in r]
    # Copied answers (identical prompt + response) inherit the verdict of their source when that
    # verdict comes from the same judge model; otherwise they are judged like any other instance.
    from f0_bridge import f0_scores
    ref = f0_scores()
    todo = []
    for r in own:
        src = r.get("copied_from")
        v = (scored.get(src) or ref.get(src)) if src else None
        if v and v.get("judge_model", "").split(".anthropic.")[-1] == jid.split(".anthropic.")[-1] and ".anthropic." in jid:
            out = dict(v); out.update({"key": r["key"], "method": r["method"], "budget": r["budget"], "copied_from": src, "usd": 0.0})
            append_jsonl(SCORES, out); scored[r["key"]] = out; done.add(r["key"])
        else:
            todo.append(r)
    if args.rejudge_f0:
        meths = set(man["candidate_oracle"]["rejudge_f0_methods"])
        todo += [r for k, r in f0_answers().items() if r["method"] in meths and r["model_key"] in ("response_a", "response_b") and k not in done]
    if args.models:
        keep = set(args.models.split(","))
        todo = [r for r in todo if r["model_key"] in keep]
    if args.limit:
        todo = todo[: args.limit]
    print(f"judge {jid}: {len(todo)} instances to score ({len(done)} already scored)")
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_instance, r, scen[r["scenario_id"]], jid, man, "judge"): r["key"] for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result(); append_jsonl(SCORES, out)
                if i % 25 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key'][:60]} score={out['checklist_score']:.2f} leak={out['distractor_leakage']} | run ${L.total - start:.2f}, total ${L.total:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e, flush=True); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            if args.max_usd is not None and L.total - start >= args.max_usd:
                print("STOP: --max-usd cap reached", flush=True); ex.shutdown(cancel_futures=True); break
    print(f"\n{fails} failures, run spend ${L.total - start:.2f}\n{L.report()}")


if __name__ == "__main__":
    main()
