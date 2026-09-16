"""Answer generation (handoff step 6): scenario × method × budget × model.

Resumable: every record in results/raw/answers.jsonl is keyed by
scenario_id|method|budget|model and existing keys are skipped, so a crash or a
budget stop never forces re-running finished instances. --dry-run builds every
context, counts tokens, and prints a cost estimate without any LLM call.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_methods import BUDGETED, METHODS, build_context, n_tokens  # noqa: E402
from cost import BudgetExceeded, ledger, price  # noqa: E402
from llm import ROOT, append_jsonl, complete, load_manifest  # noqa: E402
from metrics import selection_metrics  # noqa: E402
from schema import load_all  # noqa: E402

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
ASSUMED_OUTPUT_TOKENS = 350   # only for the dry-run estimate; real runs log actual usage


def instance_key(scenario_id: str, method: str, budget, model: str) -> str:
    return f"{scenario_id}|{method}|{budget if budget is not None else '-'}|{model}"


def existing_keys() -> set[str]:
    keys = set()
    if ANSWERS.exists():
        for line in ANSWERS.read_text().splitlines():
            if line.strip():
                try:
                    keys.add(json.loads(line)["key"])
                except json.JSONDecodeError:
                    pass
    return keys


def plan_instances(scenarios, manifest, methods, model_keys):
    budgets = manifest["context_methods"]["window_budgets_tokens"]
    for s in scenarios:
        for mk in model_keys:
            model = manifest["models"][mk]["id"]
            for m in methods:
                for b in (budgets if m in BUDGETED else [None]):
                    yield s, mk, model, m, b


def run_one(s, model_key, model, method, budget, manifest, embedder, system_prompt, dry_run):
    cfg = {"budget": budget, "model": model, "embedder": embedder}
    if dry_run and method == "rolling_summary":
        # don't pay for summaries in a dry run; approximate with the sliding window plus ~200 summary tokens
        ctx = build_context(s, "sliding_window", cfg)
        ctx.context_tokens += 200
        ctx.method = "rolling_summary"
    else:
        ctx = build_context(s, method, cfg)
    key = instance_key(s.scenario_id, method, budget, model)
    rec = {
        "key": key, "scenario_id": s.scenario_id, "family": s.family, "method": method, "budget": budget,
        "model_key": model_key, "model": model, "selected_turn_ids": ctx.selected_turn_ids,
        "context_tokens": ctx.context_tokens, "build_latency_s": round(ctx.build_latency_s, 4),
        "summary_text": ctx.summary_text, "summarized_turn_ids": ctx.summarized_turn_ids,
        "stale_superseder_missing": ctx.stale_superseder_missing,
        **selection_metrics(s, ctx.selected_turn_ids),
    }
    if dry_run:
        rec["est_input_tokens"] = n_tokens(system_prompt) + n_tokens(ctx.prompt_text)
        return rec
    mcfg = manifest["models"][model_key]
    res = complete(model, ctx.prompt_text, system=system_prompt, temperature=mcfg["temperature"],
                   max_tokens=mcfg["max_tokens"], purpose="answer", ref=key)
    rec.update({
        "system_prompt": system_prompt, "prompt": ctx.prompt_text, "response": res.text,
        "model_reported": res.model_reported, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
        "answer_latency_s": round(res.latency_s, 3), "stop_reason": res.stop_reason,
        "usd": round(price(model, res.input_tokens, res.output_tokens, manifest), 6), "ts": time.time(),
    })
    append_jsonl(ANSWERS, rec)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build contexts, estimate cost, no LLM calls")
    ap.add_argument("--models", default="response_a,response_b")
    ap.add_argument("--methods", default=",".join(METHODS))
    ap.add_argument("--scenarios", default=None, help="comma-separated scenario_id prefixes to include (default: all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=None, help="extra per-invocation cap on spend for this run")
    args = ap.parse_args()

    manifest = load_manifest()
    system_prompt = manifest["response_system_prompt"].strip()
    scenarios = load_all(ROOT / "data" / "scenarios")
    if args.scenarios:
        prefixes = tuple(args.scenarios.split(","))
        scenarios = [s for s in scenarios if s.scenario_id.startswith(prefixes)]
    methods = args.methods.split(",")
    model_keys = args.models.split(",")
    done = existing_keys()
    todo = [(s, mk, model, m, b) for s, mk, model, m, b in plan_instances(scenarios, manifest, methods, model_keys)
            if instance_key(s.scenario_id, m, b, model) not in done]
    print(f"{len(scenarios)} scenarios, {len(todo)} instances to run ({len(done)} already done)")
    if not todo:
        return
    embedder = None   # semantic selections come from the precomputed cache (see context_methods --precompute)
    L = ledger()
    start_spend = L.total

    if args.dry_run:
        est = {}
        rows = []
        for s, mk, model, m, b in todo:
            rec = run_one(s, mk, model, m, b, manifest, embedder, system_prompt, dry_run=True)
            usd = price(model, rec["est_input_tokens"], ASSUMED_OUTPUT_TOKENS, manifest)
            est[model] = est.get(model, 0.0) + usd
            rows.append(rec)
        import pandas as pd
        df = pd.DataFrame(rows)
        print(df.groupby(["method", "budget"], dropna=False)[["context_tokens", "context_recall", "context_sufficiency"]].mean().round(3).to_string())
        n_sum = sum(1 for r in rows if r["method"] == "rolling_summary" and r["context_tokens"] - 200 > 0 and r["context_tokens"] - 200 >= r["budget"] * 0.99)
        print("\nestimated answer cost (assuming %d output tokens/answer):" % ASSUMED_OUTPUT_TOKENS)
        for model, usd in est.items():
            print(f"  {model:48s} ${usd:7.2f}")
        print(f"  total ${sum(est.values()):.2f}  (plus up to {n_sum} short rolling-summary calls, cached per scenario×budget×model)")
        print(f"\ncurrent ledger: ${L.total:.2f}")
        return

    cap = args.max_usd
    failures = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {}
        for s, mk, model, m, b in todo:
            futs[ex.submit(run_one, s, mk, model, m, b, manifest, embedder, system_prompt, False)] = (s.scenario_id, m, b, mk)
        for i, f in enumerate(as_completed(futs), 1):
            sid, m, b, mk = futs[f]
            try:
                rec = f.result()
                if i % 10 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {sid} {m} {b} {mk}: {rec['input_tokens']}+{rec['output_tokens']} tok, "
                          f"{rec['answer_latency_s']:.1f}s | run ${L.total - start_spend:.2f}, total ${L.total:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e, flush=True)
                ex.shutdown(cancel_futures=True)
                break
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAILED {sid} {m} {b} {mk}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            if cap is not None and L.total - start_spend >= cap:
                print(f"STOP: this run reached its --max-usd cap ${cap:.2f}", flush=True)
                ex.shutdown(cancel_futures=True)
                break
    print(f"\nfinished in {time.time() - t0:.0f}s, {failures} failures, run spend ${L.total - start_spend:.2f}")
    print(L.report())


if __name__ == "__main__":
    main()
