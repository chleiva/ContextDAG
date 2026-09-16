"""Llama 4 Maverick verdicts for the ablation answers (sole judge, zero Opus). Resumable."""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import la  # noqa: E402,F401
from la import RAW, SCENARIOS, F0_SCENARIOS, SCORED, load_manifest, read_jsonl  # noqa: E402
from f05_cost import BudgetExceeded, ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402
from schema import load_all  # noqa: E402

ANSWERS = RAW / "answers.jsonl"; SCORES = SCORED / "scores.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6); args = ap.parse_args()
    man = load_manifest(); jid = man["models"]["judge"]["id"]
    scen = {s.scenario_id: s for s in load_all(SCENARIOS)} | {s.scenario_id: s for s in load_all(F0_SCENARIOS)}
    done = {r["key"] for r in read_jsonl(SCORES)}
    todo = [r for r in read_jsonl(ANSWERS) if r["key"] not in done and "response" in r]
    print(f"{len(todo)} to judge ({len(done)} done)")
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_instance, r, scen[r["scenario_id"]], jid, man, "judge"): r for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result(); r = futs[f]; out.update({"target": r["target"], "length": r["length"], "method_label": r["method_label"]}); append_jsonl(SCORES, out)
                if i % 40 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key'][:60]} score={out['checklist_score']:.2f} | run ${L.total - start:.3f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]['key']}: {type(e).__name__}: {str(e)[:160]}", flush=True)
    print(f"{fails} failures, run spend ${L.total - start:.3f}\n{L.report()}")


if __name__ == "__main__":
    main()
