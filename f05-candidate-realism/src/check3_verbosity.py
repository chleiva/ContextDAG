"""Check 3 §3.4 verbosity check: does MiniMax M2.5's margin over Haiku 4.5 survive when its answers
are truncated to Haiku's length? 40 seeded candidate_oracle@15 scenarios; the MiniMax answer is cut
to the cl100k token length of Haiku's answer on the same scenario; truncated and original MiniMax
answers and Haiku's answer are all judged by Llama 4 Maverick (fresh calls for all three so the
comparison is same-judge, same-time). Run with F05_LEDGER=check3.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import tiktoken

sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get("F05_LEDGER") != "check3":
    print("Refusing: set F05_LEDGER=check3", file=sys.stderr); sys.exit(2)
from f0_bridge import ROOT, load_manifest, load_scenarios, read_jsonl  # noqa: E402
from f05_cost import ledger  # noqa: E402
from f05_judge import judge_instance  # noqa: E402
from f05_llm import append_jsonl  # noqa: E402

OUT = ROOT / "results" / "check3"
RAW = ROOT / "results" / "scored" / "check3_verbosity_scores.jsonl"
enc = tiktoken.get_encoding("cl100k_base")


def main() -> None:
    man = load_manifest(); vc = man["check3"]["verbosity_check"]; jid = man["check3"]["replication_judge"]
    rng = np.random.default_rng(man["run"]["seed"])
    ans = {r["key"]: r for r in read_jsonl(ROOT / "results" / "raw" / "answers.jsonl")}
    scen = {s.scenario_id: s for s in load_scenarios()}
    hk = man["models"]["response_b"]["id"]; mm = man["models"]["response_c"]["id"]
    sids = sorted({r["scenario_id"] for r in ans.values() if r["model_key"] == "response_c" and r["method"] == "candidate_oracle" and r["budget"] == 15})
    pick = sorted(rng.choice(sids, size=vc["n"], replace=False).tolist())
    have = {(r["key"], r["variant"]) for r in read_jsonl(RAW)}
    L = ledger(); start = L.total
    for sid in pick:
        m_rec = ans[f"{sid}|candidate_oracle|15|{mm}"]; h_rec = ans[f"{sid}|candidate_oracle|15|{hk}"]
        h_len = len(enc.encode(h_rec["response"]))
        trunc = dict(m_rec); trunc["response"] = enc.decode(enc.encode(m_rec["response"])[:h_len])
        for variant, rec in (("minimax_original", m_rec), ("minimax_truncated", trunc), ("haiku", h_rec)):
            if (rec["key"], variant) in have:
                continue
            out = judge_instance(rec, scen[sid], jid, man, "check3-verbosity")
            out.update({"variant": variant, "answer_tokens": len(enc.encode(rec["response"])), "haiku_tokens": h_len})
            append_jsonl(RAW, out)
    rows = read_jsonl(RAW)
    df = pd.DataFrame(rows)
    summ = df.groupby("variant").agg(n=("key", "size"), checklist=("checklist_score", "mean"), answer_tokens=("answer_tokens", "mean")).round(3)
    piv = df.pivot_table(index="scenario_id", columns="variant", values="checklist_score")
    d1 = (piv["minimax_original"] - piv["haiku"]).dropna(); d2 = (piv["minimax_truncated"] - piv["haiku"]).dropna(); d3 = (piv["minimax_original"] - piv["minimax_truncated"]).dropna()
    def ci(d):
        b = d.to_numpy()[rng.integers(0, len(d), size=(5000, len(d)))].mean(axis=1); return float(d.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))
    res = {"n": int(len(piv)), "summary": summ.to_dict(), "minimax_minus_haiku_original": ci(d1), "minimax_minus_haiku_truncated": ci(d2), "truncation_cost": ci(d3),
           "spend_usd": round(L.total - start, 4)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verbosity.json").write_text(json.dumps(res, indent=2)); summ.to_csv(OUT / "verbosity.csv")
    print(summ.to_string()); print(json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1))


if __name__ == "__main__":
    main()
