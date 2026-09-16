"""Length-ablation answers. Stage 1: full_history on the spliced 30/60 sets (base full_history and
oracle_dag answers are reused from F0 / F0.5, identical prompts). Stage 2: semantic_retrieval@matched
(budget = the target's oracle_dag tokens) at base / 30 / 60. Responders a/b/c; resumable; own ledger.
`--precompute` builds the retrieval selections locally (no LLM)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import la  # noqa: E402,F401
from la import F0_SCENARIOS, RAW, SCENARIOS, instance_key, load_manifest, read_jsonl  # noqa: E402
from f05_cost import BudgetExceeded, ledger, price  # noqa: E402
from f05_llm import append_jsonl, complete  # noqa: E402
import context_methods as cm  # noqa: E402
from context_methods import _finish, build_context, n_tokens  # noqa: E402
from metrics import selection_metrics  # noqa: E402
from schema import load_all  # noqa: E402

ANSWERS = RAW / "answers.jsonl"
SEL = RAW / "semantic_selection.json"


def system_prompt() -> str:
    import yaml
    return yaml.safe_load((la.REPO / "f0-oracle-feasibility" / "manifest.yaml").read_text())["response_system_prompt"]


def targets_and_sets():
    man = load_manifest(); cfg = man["construction"]
    base_all = {s.scenario_id: s for s in load_all(F0_SCENARIOS)}
    targets = []
    for fam in cfg["families"]:
        targets += sorted([s for s in base_all.values() if s.family == fam], key=lambda s: s.scenario_id)[: cfg["per_family"]]
    spliced = {s.scenario_id: s for s in load_all(SCENARIOS)}
    return targets, spliced


def precompute() -> None:
    emb = cm.load_embedder(); out = {}
    targets, spliced = targets_and_sets()
    for t in targets:
        matched = build_context(t, "oracle_dag", {}).context_tokens
        out[f"{t.scenario_id}|matched_budget"] = matched
        for s in [t] + [spliced[k] for k in spliced if k.startswith(t.scenario_id + "__L")]:
            r = cm.semantic_retrieval(s, {"budget": matched, "embedder": emb})
            out[f"{s.scenario_id}|{matched}"] = r.selected_turn_ids
    SEL.write_text(json.dumps(out, indent=0)); print(f"wrote {len(out)} entries")


def plan(stage: int, models: list[str], man: dict):
    targets, spliced = targets_and_sets()
    sel = json.loads(SEL.read_text()) if SEL.exists() else {}
    items = []
    for t in targets:
        sets = {"base": t, **{int(k.split("__L")[1]): spliced[k] for k in spliced if k.startswith(t.scenario_id + "__L")}}
        for mk in models:
            mid = man["models"][mk]["id"]
            for L, s in sets.items():
                if stage == 1 and L != "base":
                    items.append((t.scenario_id, L, s, mk, mid, "full_history", None, "full_history"))
                if stage == 2:
                    b = sel[f"{t.scenario_id}|matched_budget"]
                    items.append((t.scenario_id, L, s, mk, mid, "semantic_retrieval", b, "semantic_retrieval@matched"))
    return items, sel


def run_one(target, L, s, mk, mid, method, budget, label, man, sel, sysp, dry):
    key = instance_key(s.scenario_id, label, None, mid)
    if method == "semantic_retrieval":
        t0 = time.time(); ctx = _finish(s, "semantic_retrieval", budget, list(sel[f"{s.scenario_id}|{budget}"]), t0)
    else:
        ctx = build_context(s, method, {})
    rec = {"key": key, "target": target, "length": L, "scenario_id": s.scenario_id, "family": s.family, "method": method, "budget": budget,
           "method_label": label, "model_key": mk, "model": mid, "selected_turn_ids": ctx.selected_turn_ids, "context_tokens": ctx.context_tokens,
           **selection_metrics(s, ctx.selected_turn_ids)}
    if dry:
        rec["est_input_tokens"] = n_tokens(sysp) + n_tokens(ctx.prompt_text); return rec
    mc = man["models"][mk]
    res = complete(mid, ctx.prompt_text, system=sysp, temperature=mc["temperature"], max_tokens=mc["max_tokens"], purpose=f"answer-stage{1 if method == 'full_history' else 2}", ref=key)
    rec.update({"system_prompt": sysp, "prompt": ctx.prompt_text, "response": res.text, "model_reported": res.model_reported, "route": res.route,
                "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "reasoning_chars": res.reasoning_chars,
                "answer_latency_s": round(res.latency_s, 3), "stop_reason": res.stop_reason,
                "usd": round(price(res.model, res.input_tokens, res.output_tokens, man), 6), "ts": time.time()})
    append_jsonl(ANSWERS, rec); return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, default=1); ap.add_argument("--precompute", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", default="response_a,response_b,response_c"); ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.precompute:
        precompute(); return
    man = load_manifest(); sysp = system_prompt()
    items, sel = plan(args.stage, args.models.split(","), man)
    done = {r["key"] for r in read_jsonl(ANSWERS)}
    todo = [it for it in items if instance_key(it[2].scenario_id, it[7], None, it[4]) not in done]
    print(f"stage {args.stage}: {len(items)} planned, {len(todo)} to do")
    if args.dry_run:
        est = sum(price(it[4], run_one(*it, man, sel, sysp, True)["est_input_tokens"], 700 if it[3] == "response_c" else 250, man) for it in todo)
        print(f"dry run est ≈ ${est:.2f}"); return
    L_ = ledger(); start = L_.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, *it, man, sel, sysp, False): it[2].scenario_id for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result()
                if i % 20 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key'][:60]} ctx={out['context_tokens']} | run ${L_.total - start:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:160]}", flush=True)
    print(f"{fails} failures, run spend ${L_.total - start:.2f}\n{L_.report()}")


if __name__ == "__main__":
    main()
