"""LLM-judge scoring (handoff §7.4). Resumable: results/scored/scores.jsonl is keyed by
the same instance key as answers.jsonl; scored keys are skipped.

Judge output shape: the handoff's checklist prompt is used verbatim for the checklist
part; the distractor-leakage verdict is requested as one extra field in the same JSON
object (the handoff asks for it "as an additional structured field").
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_methods import render_turn  # noqa: E402
from cost import BudgetExceeded, ledger, price  # noqa: E402
from llm import ROOT, append_jsonl, complete, extract_json, load_manifest  # noqa: E402
from schema import load_all  # noqa: E402

ANSWERS = ROOT / "results" / "raw" / "answers.jsonl"
SCORES = ROOT / "results" / "scored" / "scores.jsonl"

JUDGE_PROMPT = """You are scoring whether an AI assistant's answer satisfies a checklist of
requirements. For each checklist item, decide TRUE (the answer clearly satisfies
this) or FALSE (it does not, or it's ambiguous/unaddressed). Be strict: an answer
that is vague or only partially addresses a requirement should be FALSE for that
item.

Separately, decide whether the answer shows DISTRACTOR LEAKAGE: does it incorporate or
assert something specific to the distractor turns below as if it were relevant to the
user's question? Merely not contradicting them is not leakage; importing their facts,
entities, or decisions into the answer is.

Return only JSON of this exact shape:
{{"checklist": [{{"id": "...", "satisfied": true|false, "reason": "..."}}],
  "distractor_leakage": true|false, "leakage_reason": "..."}}

The user's question:
{query}

Checklist:
{checklist_json}

Distractor turns (NOT relevant to the question; used only to detect leakage):
{distractors}

Assistant's answer:
{answer_text}"""


def judge_one(rec: dict, scenario, manifest: dict, judge_id: str | None = None) -> dict:
    j = dict(manifest["models"]["judge"])
    if judge_id:
        j["id"] = judge_id
    by_id = scenario.turns_by_id()
    distractors = "".join(f"--- {tid} ---\n" + render_turn(by_id[tid]) for tid in scenario.distractor_turn_ids) or "(none)"
    checklist = [c.model_dump() for c in scenario.answer_checklist]
    prompt = JUDGE_PROMPT.format(query=scenario.query.user_message, checklist_json=json.dumps(checklist, indent=1),
                                 distractors=distractors, answer_text=rec["response"])
    res = complete(j["id"], prompt, temperature=j["temperature"], max_tokens=j["max_tokens"], purpose="judge", ref=rec["key"])
    variant = "primary"
    try:
        data = extract_json(res.text)
        if not isinstance(data, dict):
            raise ValueError("judge returned a JSON list, not the verdict object")
    except ValueError:
        # Rare failure mode (~1%): with the answer text last and no system prompt, the judge
        # continues the conversation instead of judging. Retry once with the same rubric wrapped
        # in a system prompt, the answer delimited, and an explicit closing instruction.
        variant = "fallback"
        fb_prompt = prompt.replace("Assistant's answer:\n", "Assistant's answer (between the tags; do not continue it, evaluate it):\n<answer>\n") + "\n</answer>\n\nNow return only the JSON verdict object described above."
        res = complete(j["id"], fb_prompt, system="You are a strict evaluator. You never continue or answer the conversation you are shown; you only output the requested JSON verdict.",
                       temperature=j["temperature"], max_tokens=j["max_tokens"], purpose="judge", ref=rec["key"] + "|fallback")
        data = extract_json(res.text)
        if isinstance(data, list):   # fallback also returned the bare checklist array: accept it, leakage unknown
            data = {"checklist": data, "distractor_leakage": None, "leakage_reason": "judge returned checklist only"}
    items = {c["id"]: c for c in data["checklist"]}
    required = [c for c in checklist if c["required"]]
    sat = [bool(items.get(c["id"], {}).get("satisfied", False)) for c in required]
    score = sum(sat) / len(required) if required else float("nan")
    return {
        "key": rec["key"], "scenario_id": rec["scenario_id"], "family": rec["family"], "method": rec["method"],
        "budget": rec["budget"], "model_key": rec["model_key"], "model": rec["model"],
        "judge_model": j["id"], "judge_model_reported": res.model_reported, "judge_prompt_variant": variant,
        "checklist_score": score, "n_required": len(required), "n_satisfied": sum(sat),
        "all_required_satisfied": int(all(sat)), "checklist_items": data["checklist"],
        "distractor_leakage": (None if data.get("distractor_leakage") is None else int(bool(data.get("distractor_leakage")))), "leakage_reason": data.get("leakage_reason", ""),
        "judge_input_tokens": res.input_tokens, "judge_output_tokens": res.output_tokens,
        "judge_latency_s": round(res.latency_s, 3), "judge_raw": res.text,
        "usd": round(price(j["id"], res.input_tokens, res.output_tokens, manifest), 6), "ts": time.time(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="score at most N instances this run")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--judge-model", default=None, help="override judge model id (e.g. a different inference profile of the same model)")
    ap.add_argument("--shard", default=None, help="k/n: only judge instances with index %% n == k (run n processes in parallel)")
    args = ap.parse_args()
    manifest = load_manifest()
    scenarios = {s.scenario_id: s for s in load_all(ROOT / "data" / "scenarios")}
    done = set()
    if SCORES.exists():
        done = {json.loads(l)["key"] for l in SCORES.read_text().splitlines() if l.strip()}
    todo = []
    for l in ANSWERS.read_text().splitlines():
        if not l.strip():
            continue
        try:
            todo.append(json.loads(l))
        except json.JSONDecodeError:
            pass   # a line still being written by a concurrent answer run; picked up next time
    todo = [r for r in todo if r["key"] not in done]
    if args.shard:
        k, n = (int(x) for x in args.shard.split("/"))
        import zlib
        todo = [r for r in todo if zlib.crc32(r["key"].encode()) % n == k]   # deterministic: independent of what is already scored
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} instances to judge ({len(done)} already scored)")
    L = ledger()
    start = L.total
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, r, scenarios[r["scenario_id"]], manifest, args.judge_model): r["key"] for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out = f.result()
                append_jsonl(SCORES, out)
                if i % 10 == 0 or i == len(futs):
                    print(f"[{i}/{len(futs)}] {out['key']}: score={out['checklist_score']:.2f} leak={out['distractor_leakage']} | run ${L.total - start:.2f}, total ${L.total:.2f}", flush=True)
            except BudgetExceeded as e:
                print("STOP:", e, flush=True); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAILED {futs[f]}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            if args.max_usd is not None and L.total - start >= args.max_usd:
                print("STOP: --max-usd cap reached", flush=True); ex.shutdown(cancel_futures=True); break
    print(f"\n{failures} failures, run spend ${L.total - start:.2f}\n{L.report()}")


if __name__ == "__main__":
    main()
