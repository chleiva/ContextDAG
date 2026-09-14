"""Judge one answer instance with a given judge model, using F0's judge prompt verbatim
(imported from f0-oracle-feasibility/src/score_quality.py) and F0's fallback-prompt logic.
Shared by calibrate_judge.py (candidate judges) and score_f05.py (adopted judge).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import load_manifest  # noqa: E402
from f05_cost import price  # noqa: E402
from f05_llm import complete, extract_json  # noqa: E402
from context_methods import render_turn  # noqa: E402  (F0)
from score_quality import JUDGE_PROMPT  # noqa: E402  (F0; prompt text only)

FALLBACK_SYSTEM = ("You are a strict evaluator. You never continue or answer the conversation you are shown; "
                   "you only output the requested JSON verdict.")


def judge_instance(rec: dict, scenario, judge_id: str, manifest: dict | None = None, purpose: str = "judge") -> dict:
    manifest = manifest or load_manifest()
    js = manifest["models"]["judge_settings"]
    by_id = scenario.turns_by_id()
    distractors = "".join(f"--- {tid} ---\n" + render_turn(by_id[tid]) for tid in scenario.distractor_turn_ids) or "(none)"
    checklist = [c.model_dump() for c in scenario.answer_checklist]
    prompt = JUDGE_PROMPT.format(query=scenario.query.user_message, checklist_json=json.dumps(checklist, indent=1),
                                 distractors=distractors, answer_text=rec["response"])
    res = complete(judge_id, prompt, temperature=js["temperature"], max_tokens=js["max_tokens"], purpose=purpose, ref=rec["key"])
    variant = "primary"
    usd = price(judge_id, res.input_tokens, res.output_tokens, manifest)
    try:
        data = extract_json(res.text)
        if not isinstance(data, dict):
            raise ValueError("judge returned a JSON list, not the verdict object")
    except ValueError:
        variant = "fallback"
        fb_prompt = prompt.replace("Assistant's answer:\n", "Assistant's answer (between the tags; do not continue it, evaluate it):\n<answer>\n") \
            + "\n</answer>\n\nNow return only the JSON verdict object described above."
        res = complete(judge_id, fb_prompt, system=FALLBACK_SYSTEM, temperature=js["temperature"], max_tokens=js["max_tokens"],
                       purpose=purpose, ref=rec["key"] + "|fallback")
        usd += price(judge_id, res.input_tokens, res.output_tokens, manifest)
        data = extract_json(res.text)
        if isinstance(data, list):
            data = {"checklist": data, "distractor_leakage": None, "leakage_reason": "judge returned checklist only"}
    items = {c.get("id"): c for c in data.get("checklist", []) if isinstance(c, dict)}
    required = [c for c in checklist if c["required"]]
    sat = [bool(items.get(c["id"], {}).get("satisfied", False)) for c in required]
    score = sum(sat) / len(required) if required else float("nan")
    leak = data.get("distractor_leakage")
    return {
        "key": rec["key"], "scenario_id": rec["scenario_id"], "family": rec["family"], "method": rec["method"],
        "budget": rec["budget"], "model_key": rec["model_key"], "model": rec["model"],
        "judge_model": res.model, "judge_model_reported": res.model_reported, "judge_route": res.route, "judge_prompt_variant": variant,
        "checklist_score": score, "n_required": len(required), "n_satisfied": sum(sat),
        "all_required_satisfied": int(all(sat)), "checklist_items": data.get("checklist", []),
        "distractor_leakage": (None if leak is None else int(bool(leak))), "leakage_reason": data.get("leakage_reason", ""),
        "judge_input_tokens": res.input_tokens, "judge_output_tokens": res.output_tokens,
        "judge_latency_s": round(res.latency_s, 3), "judge_raw": res.text, "usd": round(usd, 6), "ts": time.time(),
    }
