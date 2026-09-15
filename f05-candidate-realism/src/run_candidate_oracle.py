"""Candidate-realistic oracle answers (handoff §2.5, plan §4.4).

New context method `candidate_oracle` with the pool cap k carried in the budget slot of the
instance key (`scenario|candidate_oracle|15|model`). Selection = gold ancestor closure ∩ pool_k.
If the closure is not inside pool_k the instance fails open to full history (handoff §7.5) and
is flagged `recall_fallback`.

- response_a / response_b: candidate_oracle@primary_k on all scenarios; sensitivity k values are
  answered only where the selection differs from primary k (identical contexts are copied with a
  `copied_from` field, no LLM call).
- response_c (MiniMax M2.5, exploratory): full_history, oracle_dag, candidate_oracle@primary_k.

Resumable: results/raw/answers.jsonl keyed like F0. `--dry-run` prints a cost estimate only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidates import POOLS  # noqa: E402
from f0_bridge import ROOT, f0_answers, instance_key, load_f0_manifest, load_manifest, load_scenarios, read_jsonl  # noqa: E402
from f05_cost import BudgetExceeded, ledger, price  # noqa: E402
from f05_llm import append_jsonl, complete  # noqa: E402
from context_methods import _finish, build_context, n_tokens  # noqa: E402  (F0)
from metrics import selection_metrics  # noqa: E402  (F0)

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
F0_ANS = f0_answers()

# F0's rolling_summary calls `llm.complete` from F0's Anthropic-only client and caches summaries in
# F0's summaries.jsonl. Route those calls through F0.5's multi-backend client (so MiniMax can write its
# own summaries and spend lands on the F0.5 ledger in force) and keep F0.5's summaries in its own cache.
import context_methods as _cm  # noqa: E402
import llm as _f0_llm  # noqa: E402
import f05_llm as _f05_llm  # noqa: E402


def _patched_complete(model, prompt, **kw):
    if not _f05_llm.is_anthropic(model):
        kw["max_tokens"] = max(kw.get("max_tokens", 400), 2000)     # reasoning models spend tokens before the summary text
    return _f05_llm.complete(model, prompt, **kw)


_f0_llm.complete = _patched_complete
_cm.SUMMARY_CACHE = ROOT / "results" / "raw" / "summaries.jsonl"


def parse_methods(spec: str) -> list[tuple[str, int | None]]:
    out = []
    for m in spec.split(","):
        m = m.strip()
        if not m:
            continue
        name, _, b = m.partition("@")
        out.append((name, int(b) if b else None))
    return out


def candidate_oracle(scenario, pool_rec: dict, k: int):
    t0 = time.time()
    ranked = pool_rec["ranked"][:k]
    closure = pool_rec["gold_closure"]
    missing = [t for t in closure if t not in ranked]
    if missing:
        sel = [t.turn_id for t in scenario.history]           # fail open: full history
    else:
        sel = [t for t in closure]
    ctx = _finish(scenario, "candidate_oracle", k, sorted(sel), t0)
    extra = {"recall_fallback": int(bool(missing)), "missing_gold_turns": missing, "pool_k": ranked, "gold_closure": closure}
    return ctx, extra


def plan(man: dict, scenarios, pools: dict, models: list[str], extra_methods: str | None = None) -> list[tuple]:
    pk = man["candidate_generator"]["primary_k"]
    sens = man["candidate_oracle"]["sensitivity_k"]
    items = []
    for mk in models:
        mid = man["models"][mk]["id"]
        methods = man["models"][mk].get("methods", ["candidate_oracle"])
        if extra_methods:
            for name, b in parse_methods(extra_methods):
                for s in scenarios:
                    items.append((s, mk, mid, name, b))
            continue
        for s in scenarios:
            for m in methods:
                if m == "candidate_oracle":
                    items.append((s, mk, mid, m, pk))
                    if mk in ("response_a", "response_b"):
                        for k in sens:
                            items.append((s, mk, mid, m, k))
                else:
                    items.append((s, mk, mid, m, None))
    return items


def run_one(s, mk, mid, method, k, man, f0m, pools, system_prompt, dry_run, done: dict):
    key = instance_key(s.scenario_id, method, k, mid)
    if method == "candidate_oracle":
        ctx, extra = candidate_oracle(s, pools[s.scenario_id], k)
    else:
        ctx, extra = build_context(s, method, {"budget": k, "model": mid}), {}
        if ctx.summary_text is not None:
            extra = {"summary_text": ctx.summary_text, "summarized_turn_ids": ctx.summarized_turn_ids}
    rec = {"key": key, "scenario_id": s.scenario_id, "family": s.family, "method": method, "budget": k,
           "model_key": mk, "model": mid, "selected_turn_ids": ctx.selected_turn_ids, "context_tokens": ctx.context_tokens,
           "build_latency_s": round(ctx.build_latency_s, 4), "stale_superseder_missing": ctx.stale_superseder_missing,
           **extra, **selection_metrics(s, ctx.selected_turn_ids)}
    if dry_run:
        rec["est_input_tokens"] = n_tokens(system_prompt) + n_tokens(ctx.prompt_text)
        return rec
    # Identical context, identical deterministic (temperature 0) prompt: copy the existing answer, don't re-bill.
    #  - a fail-open fallback renders exactly the full_history context -> copy the full_history answer
    #    (F0's for response_a/b, F0.5's own for response_c);
    #  - a sensitivity k whose selection equals the primary-k selection -> copy the primary-k answer.
    if method == "candidate_oracle":
        src = None
        if extra.get("recall_fallback"):
            fkey = instance_key(s.scenario_id, "full_history", None, mid)
            src = done.get(fkey) or F0_ANS.get(fkey)
        elif k != man["candidate_generator"]["primary_k"]:
            pkey = instance_key(s.scenario_id, method, man["candidate_generator"]["primary_k"], mid)
            src = done.get(pkey)
        if src and src.get("selected_turn_ids") == ctx.selected_turn_ids and "response" in src:
            out = dict(src); out.update({"key": key, "method": method, "budget": k, **extra, "copied_from": src["key"], "usd": 0.0, "ts": time.time()})
            out.update(selection_metrics(s, ctx.selected_turn_ids))
            append_jsonl(ANSWERS, out)
            return out
    mcfg = man["models"][mk]
    res = complete(mid, ctx.prompt_text, system=system_prompt, temperature=mcfg["temperature"], max_tokens=mcfg["max_tokens"], purpose="answer", ref=key)
    rec.update({"system_prompt": system_prompt, "prompt": ctx.prompt_text, "response": res.text, "model_reported": res.model_reported, "route": res.route,
                "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "reasoning_chars": res.reasoning_chars,
                "answer_latency_s": round(res.latency_s, 3), "stop_reason": res.stop_reason,
                "usd": round(price(mid, res.input_tokens, res.output_tokens, man), 6), "ts": time.time()})
    append_jsonl(ANSWERS, rec)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", default="response_a,response_b,response_c")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--extra-methods", default=None, help="e.g. 'semantic_retrieval@1024,rolling_summary@2048': run only these for --models")
    args = ap.parse_args()
    man, f0m = load_manifest(), load_f0_manifest()
    system_prompt = f0m["response_system_prompt"]
    scenarios = load_scenarios()
    pools = {r["scenario_id"]: r for r in json.loads(POOLS.read_text())}
    done = {r["key"]: r for r in read_jsonl(ANSWERS)}
    items = plan(man, scenarios, pools, args.models.split(","), args.extra_methods)
    pk = man["candidate_generator"]["primary_k"]
    # primary-k instances first so sensitivity copies can find them
    items.sort(key=lambda it: (0 if (it[3] != "candidate_oracle" or it[4] == pk) else 1))
    todo = [it for it in items if instance_key(it[0].scenario_id, it[3], it[4], it[2]) not in done]
    print(f"{len(items)} planned, {len(done)} already answered, {len(todo)} to do")
    if args.dry_run:
        est, n_calls, fb = 0.0, 0, 0
        for s, mk, mid, m, k in todo:
            rec = run_one(s, mk, mid, m, k, man, f0m, pools, system_prompt, True, done)
            fb += rec.get("recall_fallback", 0)
            out_tok = 700 if mk == "response_c" else 230
            est += price(mid, rec["est_input_tokens"], out_tok, man); n_calls += 1
        print(f"dry run: {n_calls} calls (upper bound; identical sensitivity contexts will be copied), {fb} fail-open fallbacks, est ≈ ${est:.2f}")
        return
    L = ledger(); start = L.total; fails = 0
    # phase 1: everything at primary k / non-candidate methods, in parallel; phase 2: sensitivity (needs phase-1 records)
    phase1 = [it for it in todo if it[3] != "candidate_oracle" or it[4] == pk]
    phase2 = [it for it in todo if it not in phase1]
    for phase, batch in (("primary", phase1), ("sensitivity", phase2)):
        if not batch:
            continue
        print(f"-- {phase}: {len(batch)} instances")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_one, s, mk, mid, m, k, man, f0m, pools, system_prompt, False, done): (s.scenario_id, mk, m, k) for s, mk, mid, m, k in batch}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    out = f.result(); done[out["key"]] = out
                    if i % 20 == 0 or i == len(futs):
                        print(f"[{i}/{len(futs)}] {out['key'][:60]} ctx={out['context_tokens']} fb={out.get('recall_fallback', '-')} | run ${L.total - start:.2f}, total ${L.total:.2f}", flush=True)
                except BudgetExceeded as e:
                    print("STOP:", e, flush=True); ex.shutdown(cancel_futures=True); return
                except Exception as e:  # noqa: BLE001
                    fails += 1; print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                if args.max_usd is not None and L.total - start >= args.max_usd:
                    print("STOP: --max-usd cap reached", flush=True); ex.shutdown(cancel_futures=True); return
    print(f"\n{fails} failures, run spend ${L.total - start:.2f}\n{L.report()}")


if __name__ == "__main__":
    main()
