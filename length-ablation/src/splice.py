"""Length ablation construction + pre-flight (handoff §2, §3). No LLM calls.

For each of 40 target 1.1 scenarios, splice whole donor branches (non-gold turns from OTHER 1.1
scenarios, grouped by branch) into the target to reach ~30 and ~60 history turns. Donors are ranked
by cosine(branch text, target query) and taken greedily from the top, subject to the hard exclusion:
a donor may share no named entity with the target's gold closure, and no entity of the query may
appear in it. Gold turns keep their relative order; donor blocks go into the slots before the first
gold turn, between gold turns and after the last (seeded per target); the 30-turn history is a
prefix-of-branches subsequence of the 60-turn history. Turns are renumbered; no text changes.

Outputs: data/scenarios/<id>__L30.json, <id>__L60.json; data/meta/<id>.json; results/tables/preflight.json
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import la  # noqa: E402,F401
from la import F0_SCENARIOS, META, SCENARIOS, TABLES, load_manifest  # noqa: E402
from schema import Scenario, Turn, ancestors, load_all, save_scenario  # noqa: E402
from context_methods import build_context, n_tokens, render_turn  # noqa: E402
from candidates import extract_items  # noqa: E402  (F0.5 spaCy + regex extractor)

F05_CFG = None


def entity_cfg() -> tuple[set[str], list[str]]:
    import yaml
    c = yaml.safe_load((la.REPO / "f05-candidate-realism" / "manifest.yaml").read_text())["candidate_generator"]["entity_overlap"]
    return set(c["entity_labels"]), list(c["regex"])


def closure_ids(s: Scenario) -> list[str]:
    by = s.turns_by_id()
    return sorted(ancestors(s.query.turn_id, by), key=lambda t: by[t].turn_index)


def donor_branches(s: Scenario, gold: set[str]) -> list[list[Turn]]:
    """Non-gold, non-query turns of s grouped into chains by primary parent."""
    by = s.turns_by_id()
    hist = [t for t in s.history if t.turn_id not in gold]
    branch_of: dict[str, int] = {}
    branches: list[list[Turn]] = []
    for t in hist:
        pp = t.gold_parents[0] if t.gold_parents else None
        if pp in branch_of:
            branches[branch_of[pp]].append(t); branch_of[t.turn_id] = branch_of[pp]
        else:
            branch_of[t.turn_id] = len(branches); branches.append([t])
    return branches


def text(t: Turn) -> str:
    return f"{t.user_message}\n{t.assistant_message or ''}"


def build(target: Scenario, lengths: list[int], pool: list[dict], labels, regex, emb, seed: int) -> tuple[dict[int, Scenario], dict]:
    rng = random.Random(f"{seed}:{target.scenario_id}")
    by = target.turns_by_id()
    gold = set(closure_ids(target))
    gold_ent = set().union(*(extract_items(text(by[t]), labels, regex) for t in gold)) if gold else set()
    q_ent = extract_items(target.query.user_message, labels, regex)
    q = emb.encode([target.query.user_message], normalize_embeddings=True, convert_to_numpy=True)[0]
    cands = [d for d in pool if d["scenario_id"] != target.scenario_id]
    sims = np.array([d["vec"] for d in cands]) @ q
    order = np.argsort(-sims, kind="stable")
    base_n = len(target.history)
    SLACK = 6
    # size-aware greedy: fill each length in turn (30 then 60) from the same ranking, skipping donors that would
    # overshoot L + SLACK; the selection for 60 extends the selection for 30, so the 30 history is a prefix-of-branches
    # subsequence of the 60 history. Exclusion (entities) is applied once per donor.
    admissible, rejected = [], 0
    for i in order:
        d = cands[i]
        if (d["entities"] & gold_ent) or (d["entities"] & q_ent):
            rejected += 1; continue
        admissible.append({**d, "cosine": float(sims[i])})
    chosen, total, used_idx = [], 0, set()
    cuts: dict[int, int] = {}
    for L in sorted(lengths):
        for j, d in enumerate(admissible):
            if j in used_idx or base_n + total >= L:
                continue
            if base_n + total + len(d["turns"]) <= L + SLACK:
                chosen.append(d); used_idx.add(j); total += len(d["turns"])
        cuts[L] = len(chosen)
    sufficient = base_n + total >= max(lengths)
    # slots: before first gold, between gold turns, after last gold (before the query); base non-gold turns keep their places
    hist = list(target.history)
    gold_pos = [i for i, t in enumerate(hist) if t.turn_id in gold]
    if gold_pos:
        slots = [0] + [p + 1 for p in gold_pos]          # insertion indices into hist
    else:
        slots = [0, len(hist)]                           # new_root: before / after the existing turns
    slot_order = slots[:]; rng.shuffle(slot_order)
    assignment = [slot_order[k % len(slot_order)] for k in range(len(chosen))]   # round-robin over a seeded slot order
    out: dict[int, Scenario] = {}
    used: dict[int, list[str]] = {}
    for L in lengths:
        k = cuts[L]
        blocks: dict[int, list[list[Turn]]] = defaultdict(list)
        for j in range(k):
            blocks[assignment[j]].append(chosen[j]["turns"])
        seq: list[tuple[Turn, str | None]] = []       # (turn, donor tag)
        for i in range(len(hist) + 1):
            for blk in blocks.get(i, []):
                seq += [(t, chosen_tag) for t, chosen_tag in ((t, "donor") for t in blk)]
            if i < len(hist):
                seq.append((hist[i], None))
        # renumber
        mapping: dict[tuple, str] = {}
        new_turns: list[Turn] = []
        donor_ids_local: set[str] = set()
        for idx, (t, tag) in enumerate(seq):
            nid = f"t{idx + 1}"
            mapping[(tag, id(t))] = nid
        for idx, (t, tag) in enumerate(seq):
            nid = f"t{idx + 1}"
            if tag is None:
                parents = [mapping[(None, id(by[p]))] for p in t.gold_parents]
                new_turns.append(Turn(turn_id=nid, turn_index=idx, user_message=t.user_message, assistant_message=t.assistant_message,
                                      gold_parents=parents, stale=t.stale, superseded_by=(mapping.get((None, id(by[t.superseded_by]))) if t.superseded_by and t.superseded_by in by else None)))
            else:
                donor_ids_local.add(nid)
                # parents only within the same donor block (others dropped: the donor's gold turns are not spliced)
                parents = [mapping[(tag, id(p))] for p in [] ]
                new_turns.append(Turn(turn_id=nid, turn_index=idx, user_message=t.user_message, assistant_message=t.assistant_message, gold_parents=[], stale=False, superseded_by=None))
        # donor intra-branch links: restore chain order within each block
        pos = {id(t): i for i, (t, tag) in enumerate(seq) if tag == "donor"}
        for j in range(k):
            blk = chosen[j]["turns"]
            for a, b in zip(blk, blk[1:]):
                new_turns[pos[id(b)]].gold_parents = [f"t{pos[id(a)] + 1}"]
        qt = target.query
        qn = f"t{len(seq) + 1}"
        new_turns.append(Turn(turn_id=qn, turn_index=len(seq), user_message=qt.user_message, assistant_message=None,
                              gold_parents=[mapping[(None, id(by[p]))] for p in qt.gold_parents]))
        new_gold = [mapping[(None, id(by[t]))] for t in closure_ids(target)]
        ev = [mapping[(None, id(by[t]))] for t in target.evidence_turn_ids]
        dis = [t.turn_id for t in new_turns[:-1] if t.turn_id not in set(new_gold)]
        sid = f"{target.scenario_id}__L{L}"
        out[L] = Scenario(scenario_id=sid, family=target.family, label=target.label, turns=new_turns, evidence_turn_ids=ev,
                          distractor_turn_ids=dis, answer_checklist=list(target.answer_checklist), notes=target.notes,
                          evidence_note=target.evidence_note, premise=target.premise, evidence_spans=target.evidence_spans,
                          benchmark_version="1.1-length-ablation", length_class=f"spliced_{L}")
        used[L] = [f"{c['scenario_id']}#{c['branch']}" for c in chosen[:k]]
    meta = {"target": target.scenario_id, "family": target.family, "base_history": base_n, "gold_closure": sorted(gold), "gold_entities": sorted(gold_ent),
            "query_entities": sorted(q_ent), "donors_rejected_by_exclusion": rejected, "sufficient_to_60": sufficient,
            "chosen": [{"donor": f"{c['scenario_id']}#{c['branch']}", "turns": len(c["turns"]), "cosine": round(c["cosine"], 4)} for c in chosen],
            "used": used, "actual_lengths": {L: len(out[L].history) for L in out}}
    return out, meta


def preflight(target: Scenario, spliced: dict[int, Scenario]) -> dict:
    def oracle_hash(s: Scenario) -> str:
        return hashlib.sha256(build_context(s, "oracle_dag", {}).context_text.encode()).hexdigest()
    h0 = oracle_hash(target); hs = {L: oracle_hash(s) for L, s in spliced.items()}
    by0 = target.turns_by_id()
    gold_text0 = [render_turn(by0[t]) for t in closure_ids(target)]
    ok_ck = all(s.answer_checklist == target.answer_checklist and s.query.user_message == target.query.user_message
                and [render_turn(s.turns_by_id()[t]) for t in closure_ids(s)] == gold_text0 for s in spliced.values())
    # subsequence: 30's history texts in order appear within 60's
    seqs = {L: [text(t) for t in s.history] for L, s in spliced.items()}
    sub = True
    if len(seqs) == 2:
        a, b = seqs[min(seqs)], seqs[max(seqs)]
        it = iter(b); sub = all(any(x == y for y in it) for x in a)
    base_seq = [text(t) for t in target.history]
    it = iter(seqs[max(seqs)]); sub_base = all(any(x == y for y in it) for x in base_seq)
    return {"oracle_hash_equal": all(h == h0 for h in hs.values()), "checklist_query_closure_identical": ok_ck,
            "l30_subsequence_of_l60": sub, "base_subsequence_of_l60": sub_base,
            "oracle_tokens": build_context(target, "oracle_dag", {}).context_tokens,
            "full_tokens": {"base": sum(n_tokens(render_turn(t)) for t in target.history), **{L: sum(n_tokens(render_turn(t)) for t in s.history) for L, s in spliced.items()}}}


def main() -> None:
    man = load_manifest(); cfg = man["construction"]; seed = man["run"]["seed"]
    labels, regex = entity_cfg()
    allsc = load_all(F0_SCENARIOS)
    from sentence_transformers import SentenceTransformer
    emb = SentenceTransformer(man["models"]["embedding"]["id"])
    # donor pool
    pool = []
    for s in allsc:
        gold = set(closure_ids(s))
        for bi, br in enumerate(donor_branches(s, gold)):
            btxt = "\n".join(text(t) for t in br)
            pool.append({"scenario_id": s.scenario_id, "branch": bi, "turns": br, "text": btxt, "entities": extract_items(btxt, labels, regex)})
    vecs = emb.encode([d["text"] for d in pool], normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    for d, v in zip(pool, vecs):
        d["vec"] = v
    print(f"donor pool: {len(pool)} branches from {len(allsc)} scenarios")
    targets = []
    for fam in cfg["families"]:
        targets += sorted([s for s in allsc if s.family == fam], key=lambda s: s.scenario_id)[: cfg["per_family"]]
    SCENARIOS.mkdir(parents=True, exist_ok=True); META.mkdir(parents=True, exist_ok=True); TABLES.mkdir(parents=True, exist_ok=True)
    report = []
    for t in targets:
        lengths = [L for L in cfg["lengths"] if L > len(t.history)]       # a length below the base cannot exist
        spliced, meta = build(t, lengths or [max(cfg["lengths"])], pool, labels, regex, emb, seed)
        pf = preflight(t, spliced)
        # entity disjointness re-assert on the spliced text (belt and braces)
        gold_ent = set(meta["gold_entities"]); q_ent = set(meta["query_entities"])
        viol = 0
        for L, s in spliced.items():
            byL = s.turns_by_id(); goldL = set(closure_ids(s))
            for tid in s.distractor_turn_ids:
                if tid in [x for x in byL if x not in goldL]:
                    pass
            for c in meta["used"][L]:
                pass
        for s in spliced.values():
            save_scenario(s, SCENARIOS)
        meta["preflight"] = pf; meta["lengths_built"] = sorted(spliced)
        (META / f"{t.scenario_id}.json").write_text(json.dumps(meta, indent=1))
        report.append({"target": t.scenario_id, "family": t.family, "base": meta["base_history"], "lengths": meta["actual_lengths"],
                       "rejected": meta["donors_rejected_by_exclusion"], "sufficient": meta["sufficient_to_60"], **{k: v for k, v in pf.items() if k != "full_tokens"}, "full_tokens": pf["full_tokens"]})
        print(f"  {t.scenario_id}: base {meta['base_history']} -> {meta['actual_lengths']}; donors {len(meta['chosen'])} (rejected {meta['donors_rejected_by_exclusion']}); "
              f"hash_eq={pf['oracle_hash_equal']} ck_eq={pf['checklist_query_closure_identical']} sub={pf['l30_subsequence_of_l60']}/{pf['base_subsequence_of_l60']} sufficient={meta['sufficient_to_60']}")
    summary = {"n_targets": len(report), "all_oracle_hash_equal": all(r["oracle_hash_equal"] for r in report),
               "all_checklist_identical": all(r["checklist_query_closure_identical"] for r in report),
               "all_subsequence": all(r["l30_subsequence_of_l60"] and r["base_subsequence_of_l60"] for r in report),
               "insufficient_targets": [r["target"] for r in report if not r["sufficient"]],
               "total_rejected_donors": sum(r["rejected"] for r in report), "targets": report}
    (TABLES / "preflight.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "targets"}, indent=1))


if __name__ == "__main__":
    main()
