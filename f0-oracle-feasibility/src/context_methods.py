"""The six context construction methods (handoff §4), all with one signature:

    build_context(scenario, method, config) -> ContextResult

`config` is a dict with optional keys: budget (int tokens), model (id, for rolling
summary), embedder (SentenceTransformer, for semantic retrieval).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import tiktoken

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import Scenario, Turn, ancestors  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_CACHE = ROOT / "results" / "raw" / "summaries.jsonl"
SEMANTIC_CACHE = ROOT / "results" / "raw" / "semantic_selection.json"

METHODS = ["full_history", "sliding_window", "rolling_summary", "semantic_retrieval", "oracle_tree", "oracle_dag"]
BUDGETED = {"sliding_window", "rolling_summary", "semantic_retrieval"}

_enc = tiktoken.get_encoding("cl100k_base")


def n_tokens(text: str) -> int:
    return len(_enc.encode(text))


STALE_MARKER = "[Note: the following was later revised — see below]\n"


def render_turn(t: Turn) -> str:
    body = f"User: {t.user_message}\nAssistant: {t.assistant_message}\n"
    return (STALE_MARKER + body) if t.stale else body


def turn_tokens(t: Turn) -> int:
    """Token cost of a turn as rendered (marker included), so budgets and the
    irrelevant-context ratio count exactly what the model sees."""
    return n_tokens(render_turn(t))


@dataclass
class ContextResult:
    method: str
    budget: Optional[int]
    selected_turn_ids: list[str]
    context_text: str            # rendered context only (no system prompt, no query)
    prompt_text: str             # context_text + "\n\nUser: " + query
    context_tokens: int
    build_latency_s: float
    summary_text: Optional[str] = None
    summarized_turn_ids: list[str] = field(default_factory=list)
    summary_call: Optional[dict] = None       # LLMResult dict when a summary was generated this run
    stale_superseder_missing: list[str] = field(default_factory=list)


def _finish(scenario: Scenario, method: str, budget: Optional[int], selected: list[str], t0: float,
            prefix: str = "", **extra) -> ContextResult:
    by_id = scenario.turns_by_id()
    sel_set = set(selected)
    ordered = sorted(selected, key=lambda tid: by_id[tid].turn_index)
    missing = [tid for tid in ordered if by_id[tid].stale and by_id[tid].superseded_by not in sel_set]
    context = prefix + "".join(render_turn(by_id[tid]) for tid in ordered)
    prompt = context + "\n\nUser: " + scenario.query.user_message
    return ContextResult(method=method, budget=budget, selected_turn_ids=ordered, context_text=context,
                         prompt_text=prompt, context_tokens=n_tokens(context), build_latency_s=time.time() - t0,
                         stale_superseder_missing=missing, **extra)


# ---- 1. full history -------------------------------------------------------

def full_history(scenario: Scenario, config: dict) -> ContextResult:
    t0 = time.time()
    return _finish(scenario, "full_history", None, [t.turn_id for t in scenario.history], t0)


# ---- 2. sliding window -----------------------------------------------------

def _window(scenario: Scenario, budget: int) -> tuple[list[str], list[str]]:
    """Walk back from the query including whole turns until the budget is hit.
    Returns (inside_window_ids chronological, outside_window_ids chronological)."""
    inside: list[str] = []
    used = 0
    hist = scenario.history
    i = len(hist) - 1
    while i >= 0:
        cost = turn_tokens(hist[i])
        if used + cost > budget:
            break
        inside.append(hist[i].turn_id)
        used += cost
        i -= 1
    inside.reverse()
    outside = [t.turn_id for t in hist[: i + 1]]
    return inside, outside


def sliding_window(scenario: Scenario, config: dict) -> ContextResult:
    t0 = time.time()
    inside, _ = _window(scenario, config["budget"])
    return _finish(scenario, "sliding_window", config["budget"], inside, t0)


# ---- 3. rolling summary + recent ------------------------------------------

def _summary_cache_key(scenario_id: str, budget: int, model: str) -> str:
    return f"{scenario_id}|{budget}|{model}"


def _load_summary_cache() -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if SUMMARY_CACHE.exists():
        for line in SUMMARY_CACHE.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                cache[_summary_cache_key(r["scenario_id"], r["budget"], r["model"])] = r
    return cache


_summary_cache: Optional[dict[str, dict]] = None


def rolling_summary(scenario: Scenario, config: dict) -> ContextResult:
    """Turns outside the sliding window are collapsed into one LLM summary (cached on disk,
    keyed by scenario × budget × model, so re-runs never pay for the same summary twice)."""
    global _summary_cache
    t0 = time.time()
    budget, model = config["budget"], config["model"]
    inside, outside = _window(scenario, budget)
    if not outside:
        return _finish(scenario, "rolling_summary", budget, inside, t0)
    if _summary_cache is None:
        _summary_cache = _load_summary_cache()
    key = _summary_cache_key(scenario.scenario_id, budget, model)
    call = None
    if key in _summary_cache:
        summary = _summary_cache[key]["summary"]
    else:
        from llm import append_jsonl, complete, load_manifest
        by_id = scenario.turns_by_id()
        excerpt = "".join(render_turn(by_id[tid]) for tid in outside)
        prompt = load_manifest()["context_methods"]["summary_prompt"] + ":\n\n" + excerpt
        res = complete(model, prompt, temperature=0.0, max_tokens=load_manifest()["models"]["summarizer"]["max_tokens"],
                       purpose="summary", ref=f"{scenario.scenario_id}|{budget}")
        summary = res.text.strip()
        rec = {"scenario_id": scenario.scenario_id, "budget": budget, "model": model,
               "summarized_turn_ids": outside, "summary": summary, **{f"call_{k}": v for k, v in res.to_dict().items()}}
        append_jsonl(SUMMARY_CACHE, rec)
        _summary_cache[key] = rec
        call = res.to_dict()
    prefix = "[Summary of earlier conversation]\n" + summary + "\n\n[Recent turns]\n"
    return _finish(scenario, "rolling_summary", budget, inside, t0, prefix=prefix,
                   summary_text=summary, summarized_turn_ids=outside, summary_call=call)


# ---- 4. semantic retrieval -------------------------------------------------

_embed_cache: dict[str, np.ndarray] = {}


def _embed(embedder, texts: list[str]) -> np.ndarray:
    keys = [t for t in texts if t not in _embed_cache]
    if keys:
        vecs = embedder.encode(keys, normalize_embeddings=True, show_progress_bar=False)
        for k, v in zip(keys, vecs):
            _embed_cache[k] = np.asarray(v)
    return np.stack([_embed_cache[t] for t in texts])


_semantic_cache: Optional[dict[str, list[str]]] = None


def semantic_retrieval(scenario: Scenario, config: dict) -> ContextResult:
    """If no embedder is supplied, use the on-disk selection cache written by
    `python src/context_methods.py --precompute` (keeps torch out of the long answer run)."""
    global _semantic_cache
    t0 = time.time()
    budget, embedder = config["budget"], config.get("embedder")
    if embedder is None:
        if _semantic_cache is None:
            if not SEMANTIC_CACHE.exists():
                raise RuntimeError("no embedder and no semantic selection cache; run `python src/context_methods.py --precompute`")
            _semantic_cache = json.loads(SEMANTIC_CACHE.read_text())
        key = f"{scenario.scenario_id}|{budget}"
        if key not in _semantic_cache:
            raise RuntimeError(f"semantic selection cache has no entry for {key}; re-run --precompute")
        return _finish(scenario, "semantic_retrieval", budget, list(_semantic_cache[key]), t0)
    hist = scenario.history
    docs = [f"{t.user_message}\n{t.assistant_message}" for t in hist]
    q = _embed(embedder, [scenario.query.user_message])[0]
    d = _embed(embedder, docs)
    sims = d @ q                                   # cosine (vectors are normalized)
    order = np.argsort(-sims, kind="stable")
    selected: list[str] = []
    used = 0
    for i in order:
        cost = turn_tokens(hist[i])
        if used + cost > budget:
            continue                                # skip and keep looking for smaller turns
        selected.append(hist[i].turn_id)
        used += cost
    return _finish(scenario, "semantic_retrieval", budget, selected, t0)   # _finish re-sorts chronologically


# ---- 5/6. oracle tree and oracle DAG -------------------------------------

def oracle_tree(scenario: Scenario, config: dict) -> ContextResult:
    t0 = time.time()
    sel = ancestors(scenario.query.turn_id, scenario.turns_by_id(), use_primary_only=True)
    return _finish(scenario, "oracle_tree", None, sorted(sel), t0)


def oracle_dag(scenario: Scenario, config: dict) -> ContextResult:
    t0 = time.time()
    sel = ancestors(scenario.query.turn_id, scenario.turns_by_id(), use_primary_only=False)
    return _finish(scenario, "oracle_dag", None, sorted(sel), t0)


_IMPL = {"full_history": full_history, "sliding_window": sliding_window, "rolling_summary": rolling_summary,
         "semantic_retrieval": semantic_retrieval, "oracle_tree": oracle_tree, "oracle_dag": oracle_dag}


def build_context(scenario: Scenario, method: str, config: dict | None = None) -> ContextResult:
    config = config or {}
    if method in BUDGETED and "budget" not in config:
        raise ValueError(f"{method} needs config['budget']")
    return _IMPL[method](scenario, config)


def load_embedder():
    from sentence_transformers import SentenceTransformer
    from llm import load_manifest
    return SentenceTransformer(load_manifest()["models"]["embedding"]["id"])


def precompute_semantic_cache() -> None:
    """Embed every scenario once and store the per-budget selections."""
    from llm import load_manifest
    from schema import load_all
    manifest = load_manifest()
    embedder = load_embedder()
    out: dict[str, list[str]] = {}
    for sc in load_all(ROOT / "data" / "scenarios"):
        for b in manifest["context_methods"]["window_budgets_tokens"]:
            r = semantic_retrieval(sc, {"budget": b, "embedder": embedder})
            out[f"{sc.scenario_id}|{b}"] = r.selected_turn_ids
    SEMANTIC_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SEMANTIC_CACHE.write_text(json.dumps(out, indent=0))
    print(f"wrote {len(out)} selections to {SEMANTIC_CACHE}")


if __name__ == "__main__":
    import sys as _sys
    if "--precompute" in _sys.argv:
        precompute_semantic_cache()
