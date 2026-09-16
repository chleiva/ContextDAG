"""Benchmark 1.2 Stage A: long-scenario generator (handoff §2, §3, §3.1).

Structure first, as in 1.1: the gold DAG, the distractor branches, the near-miss slot and the
history length are decided in code by a seeded RNG; the LLM only writes text. Everything the
handoff calls a "non-negotiable generation constraint" is asserted on the generated text and a
failing scenario is regenerated with the reasons fed back (≤ max_attempts):

  entity overlap      every distractor branch reuses ≥2 entities of the gold-branch registry
  domain overlap      all branches share one premise (by construction) + no signposting (1.1 rule)
  near-miss           a designated distractor turn that sounds like the query but is about another
                      entity/version/date; asserted present and cosine-checked
  no filler           every turn belongs to a branch with a directive (by construction); non-empty text
  satisfiability      every required checklist item cites evidence turns inside the gold closure
  discrimination      join families: the required items' evidence spans ≥2 gold branches
  closure ratio       recorded per scenario
  cosine gate         median cosine(distractor turn, query) ≥ 0.60 × median cosine(gold turn, query)
                      (all-mpnet-base-v2); first-attempt pass/fail is logged separately from the final set

Usage: python src/generate_long.py --dry-run          plan sizes only, no LLM
       python src/generate_long.py --count 1           one scenario per family
       python src/generate_long.py --all               8 per family
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot  # noqa: E402,F401  (sets F05_ROOT and sys.path)
from context_methods import n_tokens, render_turn  # noqa: E402
from f05_llm import append_jsonl, complete, extract_json  # noqa: E402
from generate_scenarios import DOMAINS, LABELS, ScenarioPlan, TurnPlan, _chain, _finalize, _interleave, render_outline  # noqa: E402
from pilot import META, RAW, SCENARIOS, load_manifest  # noqa: E402
from schema import ChecklistItem, Scenario, Turn, ancestors, save_scenario, validate_scenario  # noqa: E402

GEN_LOG = RAW / "generation.jsonl"
GATE_LOG = RAW / "cosine_gate_attempts.jsonl"
FAMILIES = ["two_branch_join", "three_way_join", "resume", "long_noisy_side_thread", "new_root"]


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

@dataclass
class LongPlan:
    plan: ScenarioPlan
    gold_branches: list[str]
    distractor_branches: list[str]
    near_miss_id: str
    n_history: int


def _split(rng: random.Random, total: int, k: int, lo: int, hi: int) -> list[int]:
    """k positive sizes in [lo, hi] summing to total (adjust k if impossible)."""
    k = max(1, min(k, total // lo))
    sizes = [lo] * k
    rest = total - lo * k
    while rest > 0:
        i = rng.randrange(k)
        if sizes[i] < hi:
            sizes[i] += 1; rest -= 1
        elif all(s >= hi for s in sizes):
            sizes[i] += 1; rest -= 1
    return sizes


def _distractors(rng: random.Random, cfg: dict, n_turns: int, gold_names: str, start_letter: int = 0) -> list[list[TurnPlan]]:
    k = rng.randint(*cfg["distractor_branches"])
    lo, hi = cfg["distractor_branch_turns"]
    sizes = _split(rng, n_turns, k, lo, hi)
    letters = [chr(ord("D") + start_letter + i) for i in range(len(sizes))]
    out = []
    for name, n in zip(letters, sizes):
        d = [f"Branch {name} turn {i + 1}: {'open' if i == 0 else 'continue'} a DIFFERENT sub-problem of the same project than {gold_names} "
             f"(same people, same organisation, same documents where natural), with its own concrete numbers, names and decisions; "
             f"it must reuse at least two entities from the ENTITY REGISTRY. Irrelevant to the query." for i in range(n)]
        out.append(_chain(name, n, [], d, "distractor"))
    return out


def _mark_near_miss(rng: random.Random, branches: list[list[TurnPlan]]) -> TurnPlan:
    b = rng.choice(branches)
    t = rng.choice(b[1:] if len(b) > 1 else b)
    t.directive = ("NEAR-MISS DISTRACTOR: the user asks something that SOUNDS like the final query (same kind of question, similar wording) "
                   "but about a different entity, version, date or item from the registry; the assistant answers it confidently with "
                   "specific numbers. A careless reader would mistake this turn for the answer to the final query. " + t.directive)
    return t


def build_long(family: str, rng: random.Random, cfg: dict) -> LongPlan:
    n_hist = rng.randint(*cfg["history_turns"])
    glo, ghi = cfg["gold_chain_turns"]
    if family == "two_branch_join":
        a_n, b_n = rng.randint(glo, ghi), rng.randint(glo, ghi)
        A = _chain("A", a_n, [], [f"Branch A turn {i + 1}: develop sub-problem A; establish a specific fact/decision the query will need." for i in range(a_n)], "evidence")
        B = _chain("B", b_n, [], [f"Branch B turn {i + 1}: {'open' if i == 0 else 'develop'} sub-problem B (a different concern of the same project); establish a specific fact/decision the query will need." for i in range(b_n)], "evidence")
        D = _distractors(rng, cfg, n_hist - a_n - b_n, "A and B")
        nm = _mark_near_miss(rng, D)
        body = _interleave(rng, A, B, *D)
        q = TurnPlan("Q1", "Q", [f"A{a_n}", f"B{b_n}"], "query", "QUERY: genuinely requires BOTH branch A and branch B (combines a decision from A with a constraint from B); with only one branch it cannot be answered fully.")
        gold, summary = ["A", "B"], "Two gold branches A and B, several same-domain distractor branches, query joins the last A and last B turns."
        guidance = "One item must require a specific A fact and a different item a specific B fact. The negative item names a fact from a distractor branch (or the near-miss answer) that must not appear."
    elif family == "three_way_join":
        ns = [rng.randint(glo, min(ghi, 5)) for _ in range(3)]
        G = [_chain(nm_, n, [], [f"Branch {nm_} turn {i + 1}: {'open' if i == 0 else 'develop'} sub-problem {nm_}; establish a specific fact/decision the query will need." for i in range(n)], "evidence") for nm_, n in zip("ABC", ns)]
        D = _distractors(rng, cfg, n_hist - sum(ns), "A, B and C")
        nm = _mark_near_miss(rng, D)
        body = _interleave(rng, *G, *D)
        q = TurnPlan("Q1", "Q", [f"A{ns[0]}", f"B{ns[1]}", f"C{ns[2]}"], "query", "QUERY: genuinely requires A, B AND C together (e.g. a plan that combines a decision from A, a constraint from B and a number from C).")
        gold, summary = ["A", "B", "C"], "Three gold branches A, B, C plus same-domain distractor branches; the query joins the last turn of each."
        guidance = "At least one item per gold branch, each naming that branch's specific fact, so an answer missing any branch fails an item. One negative item."
    elif family == "resume":
        a_n = rng.randint(glo, ghi)
        A = _chain("A", a_n, [], [f"Branch A turn {i + 1}: {'open sub-problem A with concrete specifics' if i == 0 else 'develop A; settle a specific detail the query will need'}." for i in range(a_n)], "evidence")
        D = _distractors(rng, cfg, n_hist - a_n, "A")
        nm = _mark_near_miss(rng, D)
        body = A + _interleave(rng, *D)      # A entirely first, then a long detour
        q = TurnPlan("Q1", "Q", [f"A{a_n}"], "query", "QUERY: returns to sub-problem A after the long detour, picking up exactly where A left off; needs specific A facts and nothing from the detour.")
        gold, summary = ["A"], "Gold branch A at the start, then a long detour of same-domain distractor branches, then the query resumes A."
        guidance = "Items name specific A facts. The negative item names a detour fact (or the near-miss answer) that must not be imported."
    elif family == "long_noisy_side_thread":
        a_n = rng.randint(2, 4)
        A = _chain("A", a_n, [], [f"Branch A turn {i + 1}: {'open' if i == 0 else 'develop'} sub-problem A; settle specific facts the query will need." for i in range(a_n)], "evidence")
        D = _distractors(rng, cfg, n_hist - a_n, "A")
        nm = _mark_near_miss(rng, D)
        body = _interleave(rng, A, *D)
        q = TurnPlan("Q1", "Q", [f"A{a_n}"], "query", "QUERY: a follow-up on sub-problem A that needs A's specific facts; the noisy side threads are irrelevant to it.")
        gold, summary = ["A"], "A short gold branch A buried in a long, noisy set of same-domain side threads; the query depends only on A."
        guidance = "Items name specific A facts. The negative item names a side-thread fact (or the near-miss answer) that must not appear."
    elif family == "new_root":
        D = _distractors(rng, cfg, n_hist, "the earlier discussion")
        nm = _mark_near_miss(rng, D)
        body = _interleave(rng, *D)
        q = TurnPlan("Q1", "Q", [], "query", "QUERY: a brand-new, self-contained question with NO dependency on anything said before (a different concern of the same project, or a general question); answerable from general knowledge plus the query text itself.")
        gold, summary = [], "Only distractor branches; the query starts a new root with an empty parent set."
        guidance = "Items check the new question is answered on its own terms; include a 'must not' item naming a specific earlier fact (e.g. the near-miss answer) that would be a spurious import."
    else:
        raise ValueError(family)
    near_id_placeholder = nm.turn_id
    turns = _finalize(body + [q])
    near_id = next(t.turn_id for t in turns if t is nm)
    ev = [t.turn_id for t in turns[:-1] if t.branch in gold]
    di = [t.turn_id for t in turns[:-1] if t.branch not in gold]
    dnames = sorted({t.branch for t in turns[:-1] if t.branch not in gold})
    plan = ScenarioPlan(family, turns, ev, di, summary, guidance)
    return LongPlan(plan, gold, dnames, near_id, len(turns) - 1)


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

PROMPT = """You are writing a realistic, LONG multi-turn conversation between a user and an AI assistant for a research benchmark on conversational context. The conversation's dependency structure has ALREADY been decided and is given below as a turn-by-turn outline. Your job is to write natural dialogue that realizes exactly that structure.

PREMISE (one project; every branch is a different sub-problem of THIS project): {premise}

STRUCTURE ({family}): {structure_summary}
Gold branches (the query depends on them): {gold}. Distractor branches (same project, irrelevant to the query): {distractors}. Near-miss turn: {near_miss}.

OUTLINE (write these {n_turns} turns, in this order, with these ids):
{outline}

RULES
1. Write every turn listed, in order, with the exact turn_id given. Do not add, drop, merge or reorder turns.
2. Each user message is 1-3 sentences; each assistant message is 3-5 sentences of concrete, specific content (numbers, names, dates, decisions). Plain prose, no markdown, no bullet lists.
3. ENTITY REGISTRY: in the first gold-branch turns (or, for new_root, the first two turns) introduce {n_entities} named entities that belong to this project - people, organisations, products, documents, places, versions - and list them in "entity_registry" as BARE NAMES exactly as they appear in the dialogue (e.g. "Mira Okafor", "Harrowfield Historical Society"; no descriptions, no parentheses). EVERY distractor branch must mention at least two registry entities by name in its turns. Distractor branches must stay inside the same project and the same domain: no unrelated topics, no small talk, no chit-chat padding; every turn advances its own sub-problem with concrete numbers, names, dates and decisions.
4. Evidence (gold) turns carry concrete, checkable facts: exact numbers, names, dates, versions, rules. Distractor turns must be plausible and on-project but must not restate, hint at, or resolve anything the query needs.
5. The NEAR-MISS turn ({near_miss}) must read like a sibling of the final query: the same kind of question, about a different registry entity/version/date/item, answered confidently with specific numbers that are NOT the correct answer to the final query.
6. The branches are INTERLEAVED, so the user moves between sub-problems many times. Every such move happens WITHOUT announcement: the user simply asks the next question, and which sub-problem it belongs to is clear from its content alone. Never write "back to", "going back", "coming back", "returning to", "getting back", "separately", "meanwhile" or any equivalent transition. BANNED in user messages (the output is rejected if any appear): "on a different note", "on a separate note", "separately", "unrelated", "switching topics", "changing the subject", "going back to", "coming back to", "back to the ...", "circling back", "one more thing", "while we're at it", "side note", "meanwhile", "different question", "new topic", and similar signposting. To change sub-problem the user simply asks the next question; to return to an earlier one the user asks a question that is only meaningful for it.
7. The final turn is the QUERY. Write only its user_message; set its assistant_message to null. The query must be natural and must not restate the facts it depends on.
8. answer_checklist: 3-4 items a third party could judge TRUE/FALSE from the gold turns plus a candidate answer. Each criterion names the specific fact/value it checks and lists "evidence_turn_ids": the gold turn ids where that fact is stated (empty list only for new_root or for the negative item). {checklist_guidance} Every item has "required": true (there are no optional items). Include exactly one negative item phrased "The answer must not ...".
9. reference_answer: a 2-5 sentence ideal answer using only the gold turns.

Return ONLY a JSON object of this exact shape, no prose before or after:
{{
  "entity_registry": ["...", "..."],
  "turns": [{{"turn_id": "t1", "user_message": "...", "assistant_message": "..."}}, ..., {{"turn_id": "tN", "user_message": "...", "assistant_message": null}}],
  "answer_checklist": [{{"id": "c1", "criterion": "...", "required": true, "evidence_turn_ids": ["t3"]}}, ...],
  "reference_answer": "...",
  "notes": "one or two sentences on which turns hold the facts the query needs and which turn is the near-miss"
}}"""


# ---------------------------------------------------------------------------
# assertions
# ---------------------------------------------------------------------------

_embedder = None


def embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(load_manifest()["models"]["embedding"]["id"])
    return _embedder


def cosine_gate(s: Scenario, cfg: dict) -> dict:
    e = embedder()
    hist = s.history
    q = e.encode([s.query.user_message], normalize_embeddings=True, convert_to_numpy=True)[0]
    d = e.encode([f"{t.user_message}\n{t.assistant_message or ''}" for t in hist], normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    sims = {t.turn_id: float(x) for t, x in zip(hist, d @ q)}
    gold = [sims[t] for t in s.evidence_turn_ids]; dis = [sims[t] for t in s.distractor_turn_ids]
    gm = float(np.median(gold)) if gold else None; dm = float(np.median(dis)) if dis else None
    ratio = (dm / gm) if (gm and dm is not None) else None
    ok = True if gm is None else (ratio is not None and ratio >= cfg["cosine_gate"]["distractor_median_over_gold_median_min"])
    return {"gold_median": gm, "distractor_median": dm, "ratio": ratio, "pass": bool(ok), "per_turn": sims}


def _bare(x) -> str:
    """Registry entries as bare names: strip parenthetical/dash descriptions the writer tends to add."""
    x = re.split(r"\s*[\(\[]|\s+[-–—]\s+|:\s", str(x), 1)[0].strip().strip("'\"")
    return x


def check_long(s: Scenario, lp: LongPlan, data: dict, cfg: dict) -> tuple[list[str], dict]:
    """Returns (errors, meta). Errors are fed back to the writer; meta is saved as the sidecar."""
    errors: list[str] = []
    by_id = s.turns_by_id(); pb = lp.plan.by_id()
    text_of = lambda tid: f"{by_id[tid].user_message}\n{by_id[tid].assistant_message or ''}".lower()  # noqa: E731
    # no filler: every non-query turn has both messages with some substance
    for t in s.history:
        if len(t.user_message) < 15 or len(t.assistant_message or "") < 40:
            errors.append(f"{t.turn_id} is too thin (user {len(t.user_message)} chars, assistant {len(t.assistant_message or '')} chars); every turn must advance its sub-problem")
    # length
    full_tokens = sum(n_tokens(render_turn(t)) for t in s.history)
    if full_tokens < cfg["min_full_history_tokens"]:
        shortest = sorted(s.history, key=lambda t: len(t.assistant_message or ""))[:8]
        for t in shortest:
            errors.append(f"{t.turn_id} is too thin (assistant {len(t.assistant_message or '')} chars); the whole history is only {full_tokens} tokens (need ≥ {cfg['min_full_history_tokens']}), so expand this turn to 4-5 concrete sentences")
    # entity registry
    reg = [_bare(x) for x in data.get("entity_registry", []) if _bare(x)]
    lo, hi = cfg["entity_registry_size"]
    if len(reg) < lo:
        errors.append(f"entity_registry has {len(reg)} entries; need {lo}-{hi}")
    gold_text = " ".join(text_of(t) for t in s.evidence_turn_ids) if s.evidence_turn_ids else " ".join(text_of(t.turn_id) for t in s.history[:2])
    eff = [x for x in reg if x.lower() in gold_text]          # entities the gold branch actually uses
    if len(eff) < cfg["min_shared_entities_per_distractor_branch"]:
        errors.append(f"only {eff} of the registry appear in the gold turns; the gold branch must introduce at least {cfg['min_shared_entities_per_distractor_branch']} registry entities by name")
    branch_hits = {}
    for b in lp.distractor_branches:
        btxt = " ".join(text_of(t.turn_id) for t in lp.plan.turns if t.branch == b)
        hits = [x for x in eff if x.lower() in btxt]
        branch_hits[b] = hits
        if len(hits) < cfg["min_shared_entities_per_distractor_branch"]:
            errors.append(f"distractor branch {b} shares only {hits} named entities with the gold branch; it must mention at least {cfg['min_shared_entities_per_distractor_branch']} of {eff} by name")
    # near-miss
    nm = lp.near_miss_id
    if nm not in s.distractor_turn_ids:
        errors.append(f"near-miss turn {nm} is not a distractor turn")
    # checklist: satisfiability + discrimination
    items = data.get("answer_checklist", [])
    closure = set(s.evidence_turn_ids)
    item_ev = {}
    for c in items:
        ev = [(f"t{x}" if re.fullmatch(r"\d+", str(x).strip()) else str(x).strip()) for x in (c.get("evidence_turn_ids") or [])]
        item_ev[c["id"]] = ev
        neg = str(c.get("criterion", "")).lower().startswith("the answer must not")
        if not neg:
            if s.family != "new_root" and not ev:
                errors.append(f"checklist item {c['id']} cites no evidence turns; every required item must be satisfiable from the gold turns")
            bad = [t for t in ev if t not in closure]
            if bad:
                errors.append(f"checklist item {c['id']} cites {bad}, which are not gold turns; required items must be satisfiable from the gold closure alone")
    if s.family in ("two_branch_join", "three_way_join"):
        branches = {pb[t].branch for c in items for t in item_ev.get(c["id"], []) if t in pb}
        if len(branches & set(lp.gold_branches)) < 2:
            errors.append(f"required items cite gold branches {sorted(branches)} only; a join needs items whose evidence spans at least two gold branches")
    # cosine gate
    gate = cosine_gate(s, cfg)
    if not gate["pass"]:
        errors.append(f"cosine gate failed: median distractor cosine {gate['distractor_median']:.2f} vs gold median {gate['gold_median']:.2f} (ratio {gate['ratio']:.2f} < {cfg['cosine_gate']['distractor_median_over_gold_median_min']}); distractor branches must stay much closer to the query's subject (same entities, same kind of details)")
    closure_ratio = len(ancestors(s.query.turn_id, by_id)) / len(s.history)
    meta = {"scenario_id": s.scenario_id, "family": s.family, "n_history": len(s.history), "full_history_tokens": full_tokens,
            "closure_ratio": closure_ratio, "entity_registry": reg, "distractor_branch_entity_hits": branch_hits, "near_miss_turn_id": nm,
            "checklist_evidence": item_ev, "cosine": {k: v for k, v in gate.items() if k != "per_turn"}, "cosine_per_turn": gate["per_turn"],
            "gold_branches": lp.gold_branches, "distractor_branches": lp.distractor_branches}
    return errors, meta


def assemble(lp: LongPlan, scenario_id: str, premise: str, data: dict) -> Scenario:
    plan = lp.plan
    got = {t["turn_id"]: t for t in data["turns"]}
    expected = [t.turn_id for t in plan.turns]
    if list(got) != expected:
        raise ValueError(f"turn ids {list(got)[:5]}... != expected (count {len(got)} vs {len(expected)})")
    turns = []
    for i, tp in enumerate(plan.turns):
        g = got[tp.turn_id]
        turns.append(Turn(turn_id=tp.turn_id, turn_index=i, user_message=(g.get("user_message") or "").strip(),
                          assistant_message=None if tp.role == "query" else (g.get("assistant_message") or "").strip(),
                          gold_parents=list(tp.gold_parents)))
    checklist = [ChecklistItem(id=c["id"], criterion=c["criterion"].strip(), required=True) for c in data.get("answer_checklist", [])]
    notes = (data.get("notes") or "").strip()
    ref = (data.get("reference_answer") or "").strip()
    if ref:
        notes = (notes + "\n\nReference answer: " + ref).strip()
    return Scenario(scenario_id=scenario_id, family=plan.family, label=LABELS[plan.family], turns=turns,
                    evidence_turn_ids=list(plan.evidence_turn_ids), distractor_turn_ids=list(plan.distractor_turn_ids),
                    answer_checklist=checklist, notes=notes, premise=premise, benchmark_version="1.2-pilot", length_class="long")


def realize(lp: LongPlan, scenario_id: str, premise: str, man: dict, rng: random.Random) -> tuple[Scenario, dict, dict]:
    gen, cfg = man["models"]["generator"], man["generation"]
    plan = lp.plan
    prompt = PROMPT.format(premise=premise, family=plan.family, structure_summary=plan.structure_summary,
                           gold=", ".join(lp.gold_branches) or "none (new root)", distractors=", ".join(lp.distractor_branches),
                           near_miss=lp.near_miss_id, n_turns=len(plan.turns), outline=render_outline(plan),
                           n_entities=f"{cfg['entity_registry_size'][0]}-{cfg['entity_registry_size'][1]}", checklist_guidance=plan.checklist_guidance)
    temperature = round(rng.uniform(*gen["temperature_range"]), 2)
    last = ""
    for attempt in range(1, gen["max_attempts"] + 1):
        p = prompt if not last else prompt + f"\n\nYour previous attempt was rejected because: {last}\nFix every listed problem and return the full JSON again."
        res = complete(gen["id"], p, temperature=temperature, max_tokens=gen["max_tokens"], purpose="generation", ref=scenario_id)
        log = {"scenario_id": scenario_id, "attempt": attempt, "temperature": temperature, "route": res.route,
               "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "latency_s": round(res.latency_s, 1), "stop_reason": res.stop_reason}
        (RAW / "attempts").mkdir(parents=True, exist_ok=True)
        (RAW / "attempts" / f"{scenario_id}_{attempt}.txt").write_text(res.text)
        try:
            data = extract_json(res.text)
            s = assemble(lp, scenario_id, premise, data)
        except Exception as e:  # noqa: BLE001
            last = f"output could not be parsed/assembled ({str(e)[:200]})"
            log["problem"] = last; append_jsonl(GEN_LOG, log); continue
        v = validate_scenario(s)
        errs, meta = check_long(s, lp, data, cfg)
        errs = list(v.errors) + errs
        append_jsonl(GATE_LOG, {"scenario_id": scenario_id, "attempt": attempt, **meta["cosine"], "all_errors": errs})
        log["errors"] = errs; log["warnings"] = v.warnings; append_jsonl(GEN_LOG, log)
        # Local defects (signposting, thin turns) get a cheap targeted rewrite of just those turns,
        # up to 2 rounds, instead of a full 9k-token regeneration.
        for rep in range(2):
            local = [e for e in errs if "topic-switch signposting" in e or "is too thin" in e]
            if not errs or len(local) != len(errs):
                break
            data = repair(data, local, gen, scenario_id, rep + 1)
            s = assemble(lp, scenario_id, premise, data)
            v = validate_scenario(s); errs, meta = check_long(s, lp, data, cfg); errs = list(v.errors) + errs
            append_jsonl(GEN_LOG, {"scenario_id": scenario_id, "attempt": attempt, "repair": rep + 1, "errors": errs})
        if not errs:
            meta["attempt_accepted"] = attempt; meta["generation_tokens"] = [res.input_tokens, res.output_tokens]
            return s, meta, log
        last = "; ".join(errs[:8])
    raise RuntimeError(f"{scenario_id}: rejected after {gen['max_attempts']} attempts: {last[:300]}")


REPAIR_PROMPT = """Below are a few turns from a long user/assistant conversation that violate our style rules, with the rule each one breaks. Rewrite ONLY these turns so the rule is satisfied, keeping every fact, number, name and the sub-problem each turn is about. For signposting violations, remove the transition phrase entirely and make the question self-contained by naming the thing it is about (e.g. "Going back to the lease, what was the deposit?" -> "What deposit did the Draft Lease v2.1 specify?"). For thin turns, expand the assistant message to 3-5 concrete sentences. Never use any of: "back to", "going back", "coming back", "returning to", "getting back", "separately", "meanwhile", "on a different note", "one more thing", "side note", "different question", "new topic".

TURNS TO FIX:
{turns}

Return ONLY a JSON object mapping turn_id to {{"user_message": "...", "assistant_message": "..."}} (assistant_message null if it was null), nothing else."""


def repair(data: dict, errors: list[str], gen: dict, scenario_id: str, round_no: int) -> dict:
    ids = []
    for e in errors:
        m = re.match(r"(t\d+)\b", e)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    by = {t["turn_id"]: t for t in data["turns"]}
    def _rule(tid: str) -> str:
        return next(e for e in errors if re.match(tid + r"\b", e))
    block = "\n\n".join(f"{tid} (rule broken: {_rule(tid)})\nuser_message: {by[tid]['user_message']}\nassistant_message: {by[tid].get('assistant_message')}" for tid in ids if tid in by)
    res = complete(gen["id"], REPAIR_PROMPT.format(turns=block), temperature=0.3, max_tokens=4000, purpose="generation-repair", ref=f"{scenario_id}|repair{round_no}")
    fixed = extract_json(res.text)
    for tid, t in fixed.items():
        if tid in by and isinstance(t, dict):
            if t.get("user_message"):
                by[tid]["user_message"] = t["user_message"]
            if by[tid].get("assistant_message") is not None and t.get("assistant_message"):
                by[tid]["assistant_message"] = t["assistant_message"]
    return data


def generate(family: str, index: int, man: dict, used: set[str]) -> None:
    sid = f"long_{family}_{index:03d}"
    if (SCENARIOS / f"{sid}.json").exists():
        print(f"  {sid}: exists, skipping"); return
    rng = random.Random(f"{man['run']['seed']}:{sid}")
    lp = build_long(family, rng, man["generation"])
    pool = [d for d in DOMAINS if d not in used] or DOMAINS
    premise = rng.choice(pool); used.add(premise)
    t0 = time.time()
    s, meta, log = realize(lp, sid, premise, man, rng)
    save_scenario(s, SCENARIOS)
    META.mkdir(parents=True, exist_ok=True)
    (META / f"{sid}.json").write_text(json.dumps(meta, indent=1))
    print(f"  wrote {sid}: {len(s.turns)} turns, {meta['full_history_tokens']} tok, closure {meta['closure_ratio']:.2f}, "
          f"cos ratio {meta['cosine']['ratio'] if meta['cosine']['ratio'] is None else round(meta['cosine']['ratio'], 2)}, attempt {log['attempt']}, {time.time() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--count", type=int, default=None); ap.add_argument("--all", action="store_true")
    ap.add_argument("--family", default=None); ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    man = load_manifest(); cfg = man["generation"]
    fams = [args.family] if args.family else cfg["families"]
    n = cfg["per_family"] if args.all else (args.count or 1)
    if args.dry_run:
        for f in fams:
            for i in range(1, n + 1):
                rng = random.Random(f"{man['run']['seed']}:long_{f}_{i:03d}")
                lp = build_long(f, rng, cfg)
                print(f"{f}_{i:03d}: history {lp.n_history}, gold {lp.gold_branches}, distractor branches {len(lp.distractor_branches)}, near-miss {lp.near_miss_id}, prompt ≈ {n_tokens(render_outline(lp.plan))} outline tokens")
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from f05_cost import BudgetExceeded, ledger
    used: set[str] = set()
    jobs = [(f, i) for f in fams for i in range(1, n + 1)]
    L = ledger(); start = L.total; fails = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(generate, f, i, man, used): (f, i) for f, i in jobs}
        for fut in as_completed(futs):
            try:
                fut.result()
            except BudgetExceeded as e:
                print("STOP:", e); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                fails += 1; print(f"FAILED {futs[fut]}: {type(e).__name__}: {str(e)[:300]}", flush=True)
    print(f"{fails} failures, run spend ${L.total - start:.2f}\n{L.report()}")


if __name__ == "__main__":
    main()
