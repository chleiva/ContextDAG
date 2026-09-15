"""Check-3 rework item 4: re-judge the 32 off-route F0.5 Opus verdicts (all in the MiniMax arm) on a
single forced route, global.anthropic.claude-opus-4-6-v1@us-east-1, and recompute the Opus MiniMax
row candidate_oracle@15 vs full_history old vs new. Exactly these 32 calls are the one waiver of the
no-new-Opus policy. Run with F05_LEDGER=check3 and F05_FORCE_ROUTE=global.anthropic.claude-opus-4-6-v1@us-east-1.
Output: results/scored/check3_rework_opus.jsonl, results/check3/rework_offroute.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get("F05_LEDGER") != "check3" or not os.environ.get("F05_FORCE_ROUTE", "").startswith("global.anthropic.claude-opus-4-6-v1@"):
    print("Refusing: set F05_LEDGER=check3 and F05_FORCE_ROUTE=global.anthropic.claude-opus-4-6-v1@us-east-1", file=sys.stderr); sys.exit(2)
from f0_bridge import ROOT, load_manifest, load_scenarios, read_jsonl  # noqa: E402
from f05_cost import ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

OUT = ROOT / "results" / "scored" / "check3_rework_opus.jsonl"
PRIMARY = "global.anthropic.claude-opus-4-6-v1@us-east-1"


def main() -> None:
    man = load_manifest()
    scen = {s.scenario_id: s for s in load_scenarios()}
    ans = {r["key"]: r for r in read_jsonl(ROOT / "results" / "raw" / "answers.jsonl")}
    scores = {}
    for r in read_jsonl(ROOT / "results" / "scored" / "scores.jsonl"):
        scores.setdefault(r["key"], r)
    off = [r for r in scores.values() if not r.get("copied_from") and r.get("judge_route") and r["judge_route"] != PRIMARY]
    print(f"{len(off)} off-route verdicts:", sorted({(r['method'], r['model_key']) for r in off}))
    have = {r["key"] for r in read_jsonl(OUT)}
    L = ledger(); start = L.total
    failed = []
    for r in off:
        if r["key"] in have:
            continue
        try:
            out = judge_instance(ans[r["key"]], scen[r["scenario_id"]], "global.anthropic.claude-opus-4-6-v1", man, "rework-opus")
        except Exception as e:  # noqa: BLE001  (e.g. the judge continues the conversation twice; keep the old verdict for that instance)
            failed.append({"key": r["key"], "error": f"{type(e).__name__}: {str(e)[:120]}"}); continue
        assert out["judge_route"] == PRIMARY, out["judge_route"]
        out["replaces_route"] = r["judge_route"]; out["old_checklist_score"] = r["checklist_score"]
        append_jsonl(OUT, out)
    new = {r["key"]: r for r in read_jsonl(OUT)}
    # recompute the MiniMax Opus row: candidate_oracle@15 vs full_history, cluster bootstrap over scenarios
    mm = man["models"]["response_c"]["id"]
    rng = np.random.default_rng(man["run"]["seed"])
    def row(use_new: bool):
        d = []
        for sid in sorted(scen):
            ka, kb = f"{sid}|candidate_oracle|15|{mm}", f"{sid}|full_history|-|{mm}"
            sa = (new.get(ka) if use_new and ka in new else scores.get(ka)); sb = (new.get(kb) if use_new and kb in new else scores.get(kb))
            if sa and sb:
                d.append(sa["checklist_score"] - sb["checklist_score"])
        d = np.array(d); b = d[rng.integers(0, len(d), size=(10000, len(d)))].mean(axis=1)
        return {"n": int(len(d)), "q_diff": float(d.mean()), "ci_low": float(np.percentile(b, 2.5)), "ci_high": float(np.percentile(b, 97.5))}
    res = {"n_rejudged": len(new), "n_offroute": len(off), "not_rejudged": failed, "route": PRIMARY, "spend_usd": round(L.total - start, 4),
           "changed_verdicts": sum(1 for r in new.values() if abs(r["checklist_score"] - r["old_checklist_score"]) > 1e-9),
           "mean_abs_score_change": float(np.mean([abs(r["checklist_score"] - r["old_checklist_score"]) for r in new.values()])),
           "minimax_cand15_vs_full_old": row(False), "minimax_cand15_vs_full_new": row(True)}
    (ROOT / "results" / "check3" / "rework_offroute.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
