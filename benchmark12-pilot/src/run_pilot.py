"""Benchmark 1.2 pilot answers (handoff §4): four arms × three responders on the 40 long scenarios.

Arms: full_history, oracle_dag, semantic_retrieval@matched (budget = that scenario's oracle_dag
token count, computed here), semantic_retrieval@1024. Retrieval uses F0's retriever (all-mpnet-base-v2,
turn-level cosine ranking, budget-greedy) with selections precomputed locally into
results/raw/semantic_selection.json so torch stays out of the answer run.

Resumable: results/raw/answers.jsonl keyed scenario|method|budget|model. --precompute builds the
selections (no LLM); --dry-run estimates cost.
"""
from __future__ import annotations
# isort: skip_file  (the path-setting import below must precede the F0 modules it makes importable)

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot  # noqa: E402,F401
import context_methods as cm  # noqa: E402
from context_methods import _finish, build_context, n_tokens  # noqa: E402
from f05_cost import BudgetExceeded, ledger, price  # noqa: E402
from f05_llm import append_jsonl, complete  # noqa: E402
from metrics import selection_metrics  # noqa: E402
from pilot import RAW, instance_key, load_manifest, load_scenarios, read_jsonl  # noqa: E402

ANSWERS = RAW / "answers.jsonl"
SEL = RAW / "semantic_selection.json"
F0_MANIFEST = yaml_f0 = None


def system_prompt() -> str:
    import yaml
    return yaml.safe_load((pilot.REPO / "f0-oracle-feasibility" / "manifest.yaml").read_text())["response_system_prompt"]


def precompute() -> None:
    """Selections for semantic_retrieval@1024 and @matched (budget = oracle_dag tokens) per scenario."""
    emb = cm.load_embedder()
    out = {}
    for s in load_scenarios():
        dag = build_context(s, "oracle_dag", {})
        matched = dag.context_tokens
        for b in (1024, matched):
            r = cm.semantic_retrieval(s, {"budget": b, "embedder": emb})
            out[f"{s.scenario_id}|{b}"] = r.selected_turn_ids
        out[f"{s.scenario_id}|matched_budget"] = matched
    SEL.write_text(json.dumps(out, indent=0))
    print(f"wrote {len(out)} entries to {SEL}")


def arms_for(s, sel: dict) -> list[tuple[str, int | None, str]]:
    """(method, budget, label) for the four arms."""
    matched = sel[f"{s.scenario_id}|matched_budget"]
    return [("full_history", None, "full_history"), ("oracle_dag", None, "oracle_dag"),
            ("semantic_retrieval", matched, "semantic_retrieval@matched"), ("semantic_retrieval", 1024, "semantic_retrieval@1024")]


def build(s, method: str, budget, sel: dict):
    if method == "semantic_retrieval":
        t0 = time.time()
        return _finish(s, "semantic_retrieval", budget, list(sel[f"{s.scenario_id}|{budget}"]), t0)
    return build_context(s, method, {})


def run_one(s, mk: str, mid: str, method: str, budget, label: str, man: dict, sel: dict, sysp: str, dry: bool) -> dict:
    key = instance_key(s.scenario_id, label, None, mid)
    ctx = build(s, method, budget, sel)
    rec = {"key": key, "scenario_id": s.scenario_id, "family": s.family, "length_class": "long", "method": method, "budget": budget,
           "method_label": label, "model_key": mk, "model": mid, "selected_turn_ids": ctx.selected_turn_ids, "context_tokens": ctx.context_tokens,
           **selection_metrics(s, ctx.selected_turn_ids)}
    if dry:
        rec["est_input_tokens"] = n_tokens(sysp) + n_tokens(ctx.prompt_text); return rec
    mc = man["models"][mk]
    res = complete(mid, ctx.prompt_text, system=sysp, temperature=mc["temperature"], max_tokens=mc["max_tokens"], purpose="answer", ref=key)
    rec.update({"system_prompt": sysp, "prompt": ctx.prompt_text, "response": res.text, "model_reported": res.model_reported, "route": res.route,
                "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "reasoning_chars": res.reasoning_chars,
                "answer_latency_s": round(res.latency_s, 3), "stop_reason": res.stop_reason,
                "usd": round(price(res.model, res.input_tokens, res.output_tokens, man), 6), "ts": time.time()})
    append_jsonl(ANSWERS, rec)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--precompute", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", default="response_a,response_b,response_c"); ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.precompute:
        precompute(); return
    man = load_manifest(); sysp = system_prompt()
    sel = json.loads(SEL.read_text())
    scen = load_scenarios()
    done = {r["key"] for r in read_jsonl(ANSWERS)}
    todo = [(s, mk, man["models"][mk]["id"], m, b, lab) for s in scen for mk in args.models.split(",") for m, b, lab in arms_for(s, sel)
            if instance_key(s.scenario_id, lab, None, man["models"][mk]["id"]) not in done]
    print(f"{len(scen)} scenarios; {len(todo)} instances to answer ({len(done)} done)")
    if args.dry_run:
        est = 0.0
        for s, mk, mid, m, b, lab in todo:
            r = run_one(s, mk, mid, m, b, lab, man, sel, sysp, True)
            est += price(mid, r["est_input_tokens"], 700 if mk == "response_c" else 250, man)
        print(f"dry run: est ≈ ${est:.2f}"); return
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, s, mk, mid, m, b, lab, man, sel, sysp, False): (s.scenario_id, mk, lab) for s, mk, mid, m, b, lab in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result()
                if i % 20 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key'][:60]} ctx={out['context_tokens']} | run ${L.total - start:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"{fails} failures, run spend ${L.total - start:.2f}\n{L.report()}")


if __name__ == "__main__":
    main()
