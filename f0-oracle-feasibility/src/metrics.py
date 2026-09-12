"""Context-selection metrics (handoff §7.3): computed from annotations only, no LLM.

Edge cases, decided once here so every method is scored identically:
- evidence empty (new_root family): recall = 1.0 and sufficiency = 1 for every method
  (nothing was required); precision = 0.0 if anything was selected, 1.0 if nothing was.
- selected empty with non-empty evidence: precision = 0.0 (nothing right was selected).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_methods import turn_tokens  # noqa: E402
from schema import Scenario  # noqa: E402


def selection_metrics(scenario: Scenario, selected_turn_ids: list[str]) -> dict:
    by_id = scenario.turns_by_id()
    sel, ev = set(selected_turn_ids), set(scenario.evidence_turn_ids)
    hit = sel & ev
    if not sel:
        precision = 1.0 if not ev else 0.0
    else:
        precision = len(hit) / len(sel)
    recall = 1.0 if not ev else len(hit) / len(ev)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    sufficiency = 1 if ev <= sel else 0
    sel_tok = sum(turn_tokens(by_id[t]) for t in sel)
    irr_tok = sum(turn_tokens(by_id[t]) for t in sel - ev)
    irrelevant_ratio = 0.0 if sel_tok == 0 else irr_tok / sel_tok
    return {
        "context_precision": precision, "context_recall": recall, "context_f1": f1,
        "context_sufficiency": sufficiency, "irrelevant_context_ratio": irrelevant_ratio,
        "n_selected": len(sel), "n_evidence": len(ev), "n_distractors_selected": len(sel & set(scenario.distractor_turn_ids)),
        "selected_turn_tokens": sel_tok,
    }


def check_invariants(scenario: Scenario, results: dict[str, list[str]]) -> list[str]:
    """Things that must hold by construction (handoff step 5). Returns a list of violations."""
    out = []
    m_full = selection_metrics(scenario, results["full_history"])
    m_dag = selection_metrics(scenario, results["oracle_dag"])
    if m_full["context_recall"] != 1.0:
        out.append(f"{scenario.scenario_id}: full_history recall {m_full['context_recall']:.2f} != 1")
    if m_dag["context_sufficiency"] != 1:
        out.append(f"{scenario.scenario_id}: oracle_dag sufficiency 0 (selected {results['oracle_dag']}, evidence {scenario.evidence_turn_ids})")
    return out


if __name__ == "__main__":
    # Cheap sanity run on whatever scenarios exist: every method except rolling summary
    # (which costs an LLM call), plus the by-construction invariants.
    import argparse

    import pandas as pd

    from context_methods import METHODS, build_context, load_embedder
    from llm import load_manifest
    from schema import load_all

    ap = argparse.ArgumentParser()
    ap.add_argument("--with-summary", action="store_true", help="also run rolling_summary (LLM calls, cached)")
    args = ap.parse_args()
    manifest = load_manifest()
    budgets = manifest["context_methods"]["window_budgets_tokens"]
    scenarios = load_all(Path(__file__).resolve().parents[1] / "data" / "scenarios")
    embedder = load_embedder()
    rows, violations = [], []
    for s in scenarios:
        sel_by_method = {}
        for m in METHODS:
            if m == "rolling_summary" and not args.with_summary:
                continue
            cfgs = [{"budget": b, "embedder": embedder, "model": manifest["models"]["response_a"]["id"]} for b in budgets] \
                if m in ("sliding_window", "rolling_summary", "semantic_retrieval") else [{}]
            for cfg in cfgs:
                r = build_context(s, m, cfg)
                met = selection_metrics(s, r.selected_turn_ids)
                rows.append({"scenario_id": s.scenario_id, "family": s.family, "method": m, "budget": r.budget,
                             "context_tokens": r.context_tokens, **met})
                if m in ("full_history", "oracle_dag"):
                    sel_by_method[m] = r.selected_turn_ids
                if r.stale_superseder_missing:
                    violations.append(f"{s.scenario_id}/{m}/{r.budget}: stale turn(s) {r.stale_superseder_missing} rendered without their superseder")
        violations += check_invariants(s, sel_by_method)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    agg = df.groupby(["method", "budget"], dropna=False)[["context_tokens", "context_precision", "context_recall", "context_f1", "context_sufficiency", "irrelevant_context_ratio"]].mean().round(3)
    print(agg.to_string())
    print(f"\n{len(scenarios)} scenarios, {len(rows)} instances")
    if violations:
        print("\nINVARIANT VIOLATIONS:")
        for v in violations:
            print("  ", v)
        sys.exit(1)
    print("all by-construction invariants hold (full_history recall = 1, oracle_dag sufficiency = 1)")
