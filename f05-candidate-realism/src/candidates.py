"""Cheap, high-recall candidate generator (handoff §2.2–2.3, spec §7.1). No LLM calls.

For each scenario the query is the last turn; the candidate pool is the deduplicated union of
five sources over the prior turns, each pool entry tagged with the sources that proposed it,
its cosine similarity to the query, and any shared entity/identifier items. The ranking used
to cap the pool at k is (number of sources desc, cosine desc, recency desc).

Structure of prior turns (branches, heads) is derived from their gold parents, i.e. it assumes
earlier routing was correct. This is stated as an assumption in the report.

Output: results/raw/candidate_pools.json  (one record per scenario)
CLI:    python src/candidates.py                 build all pools
        python src/candidates.py --show ID ...   print pools for hand-checking
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, load_manifest, load_scenarios  # noqa: E402
from schema import Scenario, Turn, ancestors  # noqa: E402  (F0)

POOLS = ROOT / "results" / "raw" / "candidate_pools.json"
SOURCES = ["active_branch", "inactive_heads", "semantic", "entity_overlap", "recency"]

# ---- entity / identifier extraction (local) ---------------------------------------------

_RE = {
    "backtick_code": re.compile(r"`([^`\n]{2,80})`"),
    "double_quoted_phrase": re.compile(r"[\"“]([^\"”\n]{3,80})[\"”]"),
    "snake_case_identifier": re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),
    "camel_case_identifier": re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b"),
}
# very generic items that would connect unrelated turns; kept short and listed in the report
STOP_ITEMS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "first", "second", "third",
              "today", "tomorrow", "yesterday", "a few", "half", "a couple", "one day", "the day", "next week", "last week",
              "this week", "a week", "a month", "a year", "monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday", "morning", "afternoon", "evening", "night", "daily", "weekly", "monthly", "annual"}

_nlp = None


def nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load(load_manifest()["candidate_generator"]["entity_overlap"]["spacy_model"], disable=["parser", "lemmatizer"])
    return _nlp


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().strip(".,;:!?'\""))


def extract_items(text: str, labels: set[str], regex_names: list[str]) -> set[str]:
    items: set[str] = set()
    for ent in nlp()(text).ents:
        if ent.label_ in labels:
            v = _norm(ent.text)
            if len(v) >= 2 and v not in STOP_ITEMS:
                items.add(v)
    for name in regex_names:
        for m in _RE[name].finditer(text):
            v = _norm(m.group(1) if _RE[name].groups else m.group(0))
            if len(v) >= 2 and v not in STOP_ITEMS:
                items.add(v)
    return items


# ---- embeddings ---------------------------------------------------------------------------

_embedder = None


def embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(load_manifest()["models"]["embedding"]["id"])
    return _embedder


def cosines(query: str, docs: list[str]) -> np.ndarray:
    e = embedder()
    q = e.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
    d = e.encode(docs, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    return d @ q


# ---- structure helpers --------------------------------------------------------------------

def turn_text(t: Turn) -> str:
    return f"{t.user_message}\n{t.assistant_message or ''}"


def primary_parent(t: Turn) -> str | None:
    return t.gold_parents[0] if t.gold_parents else None


def branch_heads(history: list[Turn]) -> list[str]:
    """Prior turns that are nobody's primary parent (leaves of the primary-parent forest)."""
    used = {primary_parent(t) for t in history if primary_parent(t)}
    return [t.turn_id for t in history if t.turn_id not in used]


# ---- the generator ------------------------------------------------------------------------

def build_pool(s: Scenario, cfg: dict) -> dict:
    hist = s.history
    by_id = s.turns_by_id()
    q = s.query
    prev = hist[-1]
    hits: dict[str, set[str]] = defaultdict(set)
    shared: dict[str, list[str]] = {}

    # 1. active branch: preceding turn and its primary-parent chain, depth-limited
    cur, depth = prev, 0
    while cur is not None and depth < cfg["active_branch_depth"]:
        hits[cur.turn_id].add("active_branch")
        pp = primary_parent(cur)
        cur = by_id.get(pp) if pp else None
        depth += 1

    # 2. heads of inactive branches
    if cfg.get("inactive_branch_heads", True):
        for tid in branch_heads(hist):
            if tid != prev.turn_id:
                hits[tid].add("inactive_heads")

    # 3. semantic top-k
    sims = cosines(q.user_message, [turn_text(t) for t in hist])
    order = np.argsort(-sims, kind="stable")
    for i in order[: cfg["semantic_top_k"]]:
        hits[hist[i].turn_id].add("semantic")
    cos = {hist[i].turn_id: float(sims[i]) for i in range(len(hist))}

    # 4. entity / identifier overlap
    eo = cfg["entity_overlap"]
    labels, regex_names = set(eo["entity_labels"]), list(eo["regex"])
    q_items = extract_items(q.user_message, labels, regex_names)
    for t in hist:
        common = q_items & extract_items(turn_text(t), labels, regex_names)
        if len(common) >= eo["min_shared_items"]:
            hits[t.turn_id].add("entity_overlap")
            shared[t.turn_id] = sorted(common)

    # 5. recency safety net
    for t in hist[-cfg["recency_n"]:]:
        hits[t.turn_id].add("recency")

    pool = [{"turn_id": tid, "turn_index": by_id[tid].turn_index, "sources": sorted(src), "cosine": round(cos[tid], 4),
             "shared_items": shared.get(tid, [])} for tid, src in hits.items()]
    closure = sorted(ancestors(q.turn_id, by_id), key=lambda x: by_id[x].turn_index)
    variant = None
    if s.evidence_spans:
        variant = sorted(set(s.evidence_spans.values()))[0]
    return {"scenario_id": s.scenario_id, "family": s.family, "variant": variant, "n_history": len(hist),
            "query_gold_parents": list(q.gold_parents), "gold_closure": closure, "evidence_turn_ids": list(s.evidence_turn_ids),
            "query_items": sorted(q_items), "pool": pool, "ranked": rank_pool(pool)}


def rank_pool(pool: list[dict], exclude_sources: set[str] | None = None) -> list[str]:
    """Ranking used to cap the pool at k. Entries with no remaining source drop out (ablation)."""
    ex = exclude_sources or set()
    rows = [(len([x for x in p["sources"] if x not in ex]), p["cosine"], p["turn_index"], p["turn_id"]) for p in pool]
    rows = [r for r in rows if r[0] > 0]
    rows.sort(key=lambda r: (-r[0], -r[1], -r[2]))
    return [r[3] for r in rows]


def build_all() -> list[dict]:
    cfg = load_manifest()["candidate_generator"]
    scenarios = load_scenarios()
    t0 = time.time()
    out = [build_pool(s, cfg) for s in scenarios]
    POOLS.parent.mkdir(parents=True, exist_ok=True)
    POOLS.write_text(json.dumps(out, indent=0))
    print(f"wrote {len(out)} candidate pools to {POOLS} in {time.time() - t0:.1f}s")
    return out


def show(rec: dict, s: Scenario) -> None:
    by_id = s.turns_by_id()
    print(f"\n=== {rec['scenario_id']} ({rec['family']}{', ' + rec['variant'] if rec['variant'] else ''}) history={rec['n_history']} "
          f"gold_closure={rec['gold_closure']} query_parents={rec['query_gold_parents']}")
    print(f"query: {s.query.user_message[:160]!r}")
    print(f"query items: {rec['query_items']}")
    ranked = rec["ranked"]
    byt = {p["turn_id"]: p for p in rec["pool"]}
    for rank, tid in enumerate(ranked, 1):
        p = byt[tid]
        mark = "GOLD" if tid in rec["gold_closure"] else "    "
        print(f"  {rank:2d}. {mark} {tid:4s} idx={p['turn_index']:2d} cos={p['cosine']:.2f} src={'+'.join(p['sources']):45s} "
              f"{('shared=' + ','.join(p['shared_items'][:3])) if p['shared_items'] else ''}  | {by_id[tid].user_message[:70]!r}")
    missing = [t for t in rec["gold_closure"] if t not in ranked]
    if missing:
        print(f"  MISSING FROM UNION: {missing}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", nargs="*", default=None, help="scenario ids to print (default: build all)")
    args = ap.parse_args()
    if args.show is None:
        build_all()
    else:
        recs = {r["scenario_id"]: r for r in json.loads(POOLS.read_text())}
        scen = {s.scenario_id: s for s in load_scenarios()}
        for sid in args.show:
            show(recs[sid], scen[sid])
