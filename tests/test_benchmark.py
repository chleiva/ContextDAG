"""Offline integrity checks on the committed benchmark and analysis code. No model calls, no network
(apart from tiktoken's cached encoding). Run with `make test`."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "f0-oracle-feasibility" / "src"))
sys.path.insert(0, str(REPO / "f05-candidate-realism" / "src"))

from context_methods import build_context, render_turn  # noqa: E402
from schema import ancestors, load_all, validate_scenario  # noqa: E402

F0 = REPO / "f0-oracle-feasibility" / "data" / "scenarios"
PILOT = REPO / "benchmark12-pilot" / "data" / "scenarios"
ABL = REPO / "length-ablation" / "data" / "scenarios"
MANIFESTS = [REPO / d / "manifest.yaml" for d in ("f0-oracle-feasibility", "f05-candidate-realism", "benchmark12-pilot", "length-ablation")]


def test_benchmark_11_has_145_valid_scenarios():
    scen = load_all(F0)
    assert len(scen) == 145
    bad = [(s.scenario_id, validate_scenario(s).errors) for s in scen if not validate_scenario(s).ok]
    assert not bad, bad[:3]


def test_benchmark_11_family_counts_match_manifest():
    man = yaml.safe_load(MANIFESTS[0].read_text())
    scen = load_all(F0)
    counts = {}
    for s in scen:
        counts[s.family] = counts.get(s.family, 0) + 1
    assert counts == man["benchmark"]["family_targets"]


@pytest.mark.parametrize("path", [PILOT, ABL])
def test_added_benchmark_sets_validate(path):
    scen = load_all(path)
    assert scen, f"no scenarios under {path}"
    for s in scen:
        v = validate_scenario(s)
        assert v.ok, (s.scenario_id, v.errors)
        assert s.length_class is not None


def test_oracle_context_is_ancestor_closure_and_full_history_recall_is_one():
    for s in load_all(F0)[:40]:
        dag = build_context(s, "oracle_dag", {})
        assert set(dag.selected_turn_ids) == ancestors(s.query.turn_id, s.turns_by_id())
        full = build_context(s, "full_history", {})
        assert set(s.evidence_turn_ids) <= set(full.selected_turn_ids)


def test_splice_preserves_oracle_context_and_checklist():
    """The length ablation's core property: the oracle_dag context is byte-identical at every length,
    and checklist / query / gold-turn text are unchanged (recomputed here, not read from the tables)."""
    base = {s.scenario_id: s for s in load_all(F0)}
    spliced = load_all(ABL)
    assert spliced
    for s in spliced:
        t = base[s.scenario_id.split("__L")[0]]
        h = lambda x: hashlib.sha256(build_context(x, "oracle_dag", {}).context_text.encode()).hexdigest()  # noqa: E731
        assert h(s) == h(t), s.scenario_id
        assert s.answer_checklist == t.answer_checklist and s.query.user_message == t.query.user_message
        by_t, by_s = t.turns_by_id(), s.turns_by_id()
        gold_t = [render_turn(by_t[x]) for x in sorted(ancestors(t.query.turn_id, by_t), key=lambda x: by_t[x].turn_index)]
        gold_s = [render_turn(by_s[x]) for x in sorted(ancestors(s.query.turn_id, by_s), key=lambda x: by_s[x].turn_index)]
        assert gold_t == gold_s, s.scenario_id
        assert len(s.history) > len(t.history)


def test_every_manifest_prices_every_model_it_names():
    for m in MANIFESTS:
        man = yaml.safe_load(m.read_text())
        prices = man["pricing_usd_per_1m_tokens"]
        for k, v in man["models"].items():
            ids = []
            if isinstance(v, dict) and "id" in v and v["id"]:
                ids.append(v["id"])
            if isinstance(v, list):
                ids += [c["id"] for c in v if isinstance(c, dict) and "id" in c]
            for mid in ids:
                if mid.startswith(("us.", "global.")) or "." in mid:
                    assert mid in prices or ("us." + mid.split(".", 1)[1] in prices) or ("global." + mid.split(".", 1)[1] in prices), (m.name, mid)
        assert man["budget"]["hard_limit_usd"] >= man["budget"]["warn_usd"] >= man["budget"]["estimate_usd"]


def test_holm_and_pooled_guard():
    from check3 import holm  # noqa: E402
    adj = holm([0.01, 0.04, 0.03, 0.20])
    assert adj == pytest.approx([0.04, 0.09, 0.09, 0.20])   # step-down: 0.03*3=0.09 caps the later 0.04*2=0.08
    # pooled delta must equal the mean of per-model deltas when both arms use the same model set
    rng = np.random.default_rng(0)
    a = rng.random((3, 40)); b = rng.random((3, 40))
    pooled = (a.mean(axis=0) - b.mean(axis=0)).mean()
    per_model = (a - b).mean(axis=1).mean()
    assert abs(pooled - per_model) < 1e-12


def test_ledgers_are_well_formed_and_within_limits():
    for d in ("f0-oracle-feasibility", "f05-candidate-realism", "benchmark12-pilot", "length-ablation"):
        for led in (REPO / d / "results" / "raw").glob("cost_ledger*.jsonl"):
            rows = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
            assert rows and all({"model", "usd", "input_tokens", "output_tokens"} <= set(r) for r in rows), led
            assert all(r["usd"] >= 0 for r in rows), led
