"""Fill F0.5_RESULTS.md (handoff §6 template, extended) from the tables written by recall.py,
calibrate_judge.py --analyze, analyze_f05.py, and the cost ledger."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_bridge import ROOT, load_manifest  # noqa: E402
from f05_cost import ledger  # noqa: E402

T = ROOT / "results" / "tables"
OUT = ROOT.parent / "docs" / "results" / "F0.5_RESULTS.md"


def md(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "" if pd.isna(x) else floatfmt.format(x))
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |")
    return "\n".join(lines)


def git_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:  # noqa: BLE001
        return "uncommitted"


def main() -> None:
    man = load_manifest()
    thr = man["f05_decision_thresholds"]
    pk = man["candidate_generator"]["primary_k"]
    cand = f"candidate_oracle@{pk}"
    rec = json.loads((T / "recall_summary.json").read_text())
    by_k = pd.read_csv(T / "recall_by_k.csv")
    fam_piv = pd.read_csv(T / "recall_by_family_pivot.csv")
    variant = pd.read_csv(T / "recall_variant.csv")
    abl = pd.read_csv(T / "recall_ablation.csv")
    attr = pd.read_csv(T / "recall_source_attribution.csv")
    misses = pd.read_csv(T / "recall_misses.csv")
    cal = pd.read_csv(T / "calibration_summary.csv")
    cal_fam = pd.read_csv(T / "calibration_by_family.csv")
    adopted = json.loads((T / "judge_adopted.json").read_text())
    summary = pd.read_csv(T / "summary.csv")
    pair = pd.read_csv(T / "pairwise.csv")
    ret = pd.read_csv(T / "retention.csv")
    fam_q = pd.read_csv(T / "by_family_checklist_pivot.csv", header=[0, 1], index_col=0)
    fb = pd.read_csv(T / "by_family_fallback_rate.csv")
    shift = pd.read_csv(T / "judge_shift.csv") if (T / "judge_shift.csv").exists() else None
    dec = json.loads((T / "decision.json").read_text())
    L = ledger()
    disp = {k: v["display"] for k, v in man["models"].items() if isinstance(v, dict) and "display" in v}

    def srow(mk, ml):
        r = summary[(summary.model_key == mk) & (summary.method_label == ml)]
        return r.iloc[0] if len(r) else None

    def prow(mk, a, b, metric, fams="all"):
        r = pair[(pair.model == mk) & (pair.a == a) & (pair.b == b) & (pair.metric == metric) & (pair.families == fams)]
        return r.iloc[0] if len(r) else None

    verdicts = {mk: dec[mk]["verdict"] for mk in ("response_a", "response_b") if isinstance(dec.get(mk), dict)}
    overall = "PASS" if verdicts and all(v == "PASS" for v in verdicts.values()) else "PIVOT"

    lines = []
    A = lines.append
    A("# F0.5 Candidate-Realism Check — Results\n")
    A(f"Run date: {date.today().isoformat()}  ")
    A(f"Manifest: `f05-candidate-realism/manifest.yaml` at commit {git_hash()} (thresholds frozen before any billed call; see `F0.5_PLAN.md` §5)  ")
    A(f"Benchmark version used: {man['run']['benchmark_version']} (145 scenarios, read from `f0-oracle-feasibility/data/scenarios`)  ")
    ad = cal[cal.judge == adopted.get("adopted_judge")]
    judge_cfg = man["models"]["judge"]
    if len(ad):
        a0 = ad.iloc[0]
        A(f"Judge: **{a0.display}** (`{a0.judge}`), calibrated against Claude Opus 4.6 on {int(a0.n_instances)} F0 instances: item κ = {a0.item_kappa:.3f}, mean |Δ score| = {a0.mean_abs_score_delta:.3f}, method ranking preserved ({a0.ranking_violations}), ${a0.usd_per_call:.4f}/call  ")
    else:
        A(f"Judge: **{judge_cfg['display']}** (`{judge_cfg['id']}`) — the F0 reference judge, retained because no cheap candidate passed the frozen calibration bar (see Judge calibration)  ")
    A(f"Response models: {disp['response_a']}, {disp['response_b']} (unchanged from F0); exploratory third arm {disp['response_c']} (plan DECISION 5, option a)  ")
    A(f"\n**Decision: {overall}** — " + "; ".join(f"{disp[mk]}: {v}" for mk, v in verdicts.items()) + f". Strict Candidate Recall@{pk} = {rec['strict_recall_at_primary_k_all']:.3f} (gate ≥ {thr['min_candidate_recall_at_k']}).\n")

    # ---- judge calibration
    A("## Judge calibration\n")
    A(f"Reference: Opus 4.6 verdicts already in F0's `scores.jsonl` (no new Opus calls). Sample: {int(cal.n_instances.max())} instances, family-proportional, both response models, methods spread over full_history / sliding_window@1024 / semantic_retrieval@1024 / oracle_tree / oracle_dag. "
      f"Adoption bar (frozen): item κ ≥ {thr['judge_calibration_min_kappa']}, mean |Δ| ≤ {thr['judge_calibration_max_score_delta']}, method ranking preserved (tie band {thr['judge_ranking_tie_band']}). Grok 4.6 could not be tested: it is gated on this Bedrock account (AccessDenied in us-east-1 and us-west-2 via `converse`).\n")
    A(md(cal[["display", "n_instances", "n_items", "item_kappa", "item_agreement", "mean_abs_score_delta", "p90_abs_score_delta", "mean_signed_delta", "leakage_kappa", "ranking_spearman", "ranking_violations", "fallback_prompt_uses", "usd_per_call", "PASS"]], "{:.4f}"))
    A("\nκ by response model (does the judge agree with Opus equally on Sonnet and Haiku answers):\n")
    A(md(cal[["display", "kappa_by_model"]]))
    fk = cal_fam[~cal_fam.family.str.startswith("[method]")].pivot(index="family", columns="judge", values="item_kappa").reset_index()
    A("\nItem κ by family:\n"); A(md(fk))
    mm = cal_fam[cal_fam.family.str.startswith("[method]")].copy()
    mm["method"] = mm.family.str.replace("[method] ", "", regex=False)
    mt = mm.pivot(index="method", columns="judge", values="cand_mean")
    mt["Opus 4.6 (reference)"] = mm.groupby("method").ref_mean.first()
    A("\nMethod means on the calibration subsample (ranking check):\n"); A(md(mt.reset_index()))
    if adopted.get("adopted_judge"):
        A(f"\nAdopted: **{adopted.get('display')}** — rule: {adopted.get('rule', 'n/a')}; passers: {', '.join(adopted.get('passers', []))}.\n")
    else:
        per = pd.read_csv(T / "calibration_per_instance.csv")
        agree_share = (per.delta.abs() < 1e-9).groupby(per.judge).mean()
        A("\n**Outcome: no candidate passed.** Every candidate clears the κ bar and preserves the method ranking, and every one fails the mean |Δ| ≤ 0.05 bar, in the same direction: all four are stricter than Opus 4.6 (negative mean signed Δ). "
          "The bar was frozen before the run and, per handoff §1.3.4, was not lowered to fit; the fallback chain (Llama 4 Maverick, then Mistral Large 3) was exhausted, so the F0 reference judge (Opus 4.6, global profile) scores every gating arm in this report. "
          "F0's full_history and oracle_dag baselines already carry Opus verdicts, so no re-judging was needed.\n")
        A("Why the |Δ| bar is hard to meet: a checklist has ~3.7 required items, so a single item disagreement moves an instance's score by ~0.25–0.33. "
          f"The share of instances on which each judge agreed with Opus on every item was: {', '.join(f'{disp_j} {v:.0%}' for disp_j, v in zip(cal.set_index('judge').loc[agree_share.index].display, agree_share.values))}. "
          "Mean |Δ| ≤ 0.05 therefore requires item agreement of roughly 95% or more, a level that Opus 4.6's own run-to-run agreement was never measured against. This is recorded as an observation for the next phase, not as a reason to move the bar after the fact.\n")

    # ---- recall
    A("## Candidate Recall@k\n")
    A(f"Candidate generator: five non-LLM sources (active-branch chain depth {man['candidate_generator']['active_branch_depth']}, inactive branch heads, top-{man['candidate_generator']['semantic_top_k']} all-mpnet-base-v2 neighbours, spaCy/regex entity overlap, last {man['candidate_generator']['recency_n']} turns), deduplicated, ranked by (sources, cosine, recency) and capped at k. "
      f"Recall target = the full gold ancestor closure (F0's oracle_dag selection). Branch structure of prior turns is read from their gold parents, i.e. the generator assumes earlier turns were routed correctly.\n")
    A(f"**Headline: strict Recall@{pk} = {rec['strict_recall_at_primary_k_all']:.3f} [{rec['ci'][0]:.3f}, {rec['ci'][1]:.3f}] over all 145 scenarios (fractional {rec['fractional_recall_at_primary_k_all']:.3f}); "
      f"excluding the 8 `new_root` scenarios (empty closure, vacuous) {rec['strict_recall_at_primary_k_excl_new_root']:.3f}; long families only {rec['strict_recall_at_primary_k_long_families']:.3f}. "
      f"Gate ≥ {thr['min_candidate_recall_at_k']}: {'PASS' if rec['passes_recall_gate'] else 'FAIL'}.**\n")
    A(f"Caveat stated up front (plan §3.4): a pool of {pk} holds the entire history on {145 - rec['n_cap_binds_at_primary_k']} of 145 scenarios, so the k={pk} cap only binds on {rec['n_cap_binds_at_primary_k']} long scenarios. "
      f"The k=5 column is where the heuristics are actually stressed: strict Recall@5 = {rec['strict_recall_at_5_all']:.3f} over all 145, {rec['strict_recall_at_5_feasible_only']:.3f} over the {rec['n_feasible_at_5']} scenarios whose closure has ≤ 5 turns (a 5-turn pool cannot hold a 6-turn chain). "
      f"The uncapped union reaches {rec['strict_recall_uncapped_all']:.3f}: the five heuristics miss {rec['gold_turns_missed_by_union']} of {rec['gold_turns_total']} gold turns outright.\n")
    A("### By k\n"); A(md(by_k[["subset", "k", "n", "strict_recall", "strict_ci_low", "strict_ci_high", "fractional_recall", "mean_pool_size", "mean_pool_frac_of_history", "n_cap_binds"]]))
    A("\n### Strict recall by family\n"); A(md(fam_piv))
    A("\n### compound_turn by sub-condition (handoff §0)\n"); A(md(variant))
    A("\n### Per-source ablation (strict recall with one source removed)\n")
    A(md(abl.pivot(index="dropped_source", columns="k", values="strict_recall").reset_index()))
    A("\n### Which sources find the gold turns (uncapped union)\n"); A(md(attr))
    um = misses[misses.k == "uncapped"]
    if len(um):
        A("\nGold turns the union never proposes:\n"); A(md(um[["scenario_id", "family", "n_history", "n_gold", "n_found", "missing"]]))
    m15 = misses[misses.k.astype(str) == str(pk)]
    if len(m15):
        A(f"\nScenarios failing strict recall at k={pk}:\n"); A(md(m15[["scenario_id", "family", "n_history", "n_gold", "n_found", "missing"]]))

    # ---- candidate oracle
    A("\n## Candidate-realistic oracle vs. F0 oracle DAG and vs. full history\n")
    A(f"`{cand}` = gold closure restricted to the size-{pk} pool; when the closure is not inside the pool the instance fails open to full history (handoff §7.5) and is counted in `recall_fallback`. "
      "All three arms below (candidate oracle, oracle_dag, full_history) are judged by the same model: the candidate-oracle and MiniMax answers by Opus 4.6 in this run, the oracle_dag and full_history baselines by Opus 4.6 in F0, so no row mixes judges. `[recall-holds]` rows exclude fallback instances.\n")
    cols = ["model_key", "method_label", "n", "n_scored", "context_tokens", "token_reduction_pct", "checklist_score", "checklist_ci_low", "checklist_ci_high", "context_precision", "context_sufficiency", "irrelevant_context_ratio", "distractor_leakage", "recall_fallback"]
    ident = pd.read_csv(T / "context_identity.csv")
    i15 = ident[(ident.model == "response_a") & (ident.method_label == cand)].iloc[0]
    i5 = ident[(ident.model == "response_a") & (ident.method_label == "candidate_oracle@5")]
    A(f"**Read this first.** Because the restricted oracle keeps exactly the gold closure whenever the pool contains it, `{cand}` selects the *same turns as F0's oracle_dag* on {100 * i15.same_context_as_oracle_dag:.1f}% of scenarios (the rest fail open). "
      f"The k={pk} rows below are therefore a near-replication of F0's oracle_dag result with freshly generated answers, not an independent measurement of candidate quality. "
      + (f"The informative sensitivity arm is k=5, where the pool is too small on {100 * i5.fallback_rate.iloc[0]:.0f}% of scenarios and the system falls open to full history: that is what a real deployment with a 5-turn budget would pay in tokens on this benchmark. " if len(i5) else "")
      + "Rows marked `[recall-holds]` are the subset where no fallback happened; at small k that subset is dominated by short scenarios, so its numbers are optimistic.\n")
    A(md(summary[cols]))
    A("\nShare of scenarios where the candidate oracle's context is identical to oracle_dag, and the fail-open rate, by k:\n")
    A(md(ident))
    A("\n### Paired bootstrap (10,000 resamples, per response model; a minus b)\n")
    A(md(pair[["model", "a", "b", "metric", "families", "n", "mean_diff", "ci_low", "ci_high"]], "{:.4f}"))
    A("\n### Advantage retention (reported, not gating — plan DECISION 4)\n")
    A("retention = (candidate − full) / (oracle DAG − full) on checklist score, same judge. The denominator is small and its CI spans zero for both models in F0, which is why this ratio is reported rather than gated.\n")
    A(md(ret))
    A("\n### Checklist score by family\n")
    for mk in ("response_a", "response_b", "response_c"):
        if mk in fam_q.columns.get_level_values(0):
            sub = fam_q[mk].reset_index()
            A(f"\n{disp[mk]}:\n"); A(md(sub))
    A("\nFail-open (fallback to full history) rate by family and k:\n"); A(md(fb))
    if (T / "compound_turn_by_variant.csv").exists():
        A("\ncompound_turn by sub-condition (checklist score):\n")
        A(md(pd.read_csv(T / "compound_turn_by_variant.csv", header=[0, 1], index_col=0).stack(0, future_stack=True).reset_index().rename(columns={"level_0": "variant", "level_1": "model_key"})))
    if shift is not None and len(shift):
        A("\n### Judge shift on the re-judged F0 baselines (same answers, Opus 4.6 vs adopted judge)\n"); A(md(shift))

    # ---- MiniMax arm
    if "response_c" in summary.model_key.values:
        A("\n## Exploratory arm: MiniMax M2.5\n")
        A("Same scenarios and prompts, three methods, same judge. This arm tests the user's hypothesis that an open-weight model at a fraction of Haiku's price is at least as good on this benchmark; it is not part of the pre-registered decision.\n")
        A(md(summary[summary.model_key == "response_c"][cols]))
        for ml in ("full_history", "oracle_dag", cand):
            pass
        ha, mi = srow("response_b", "full_history"), srow("response_c", "full_history")
        if ha is not None and mi is not None:
            per = pd.read_csv(T / "per_instance.csv")
            cst = per[(per.method_label == cand) & (per.usd > 0)].groupby("model_key").usd.mean()
            A(f"\nFull-history checklist score: Haiku 4.5 {ha.checklist_score:.3f} vs MiniMax M2.5 {mi.checklist_score:.3f}; oracle DAG: {srow('response_b', 'oracle_dag').checklist_score:.3f} vs {srow('response_c', 'oracle_dag').checklist_score:.3f}; {cand}: {srow('response_b', cand).checklist_score:.3f} vs {srow('response_c', cand).checklist_score:.3f}. "
              f"Mean output tokens per answer (MiniMax includes reasoning): {mi.output_tokens:.0f} vs Haiku {ha.output_tokens:.0f}; mean latency {mi.answer_latency_s:.1f}s vs {ha.answer_latency_s:.1f}s; "
              f"billed cost per {cand} answer: MiniMax ${cst.get('response_c', float('nan')):.4f} vs Haiku ${cst.get('response_b', float('nan')):.4f} vs Sonnet ${cst.get('response_a', float('nan')):.4f} (MiniMax at the budgeted upper-bound rate).\n")

    # ---- decision
    A("\n## Decision\n")
    A(f"Applied mechanically against the thresholds frozen in `manifest.yaml`: strict Recall@{pk} ≥ {thr['min_candidate_recall_at_k']}; `{cand}` within {thr['quality_non_inferiority_margin_pp']} pp of full_history on checklist score (same judge); ≥ {thr['min_token_reduction_pct']}% fewer context tokens than full_history with fallbacks included.\n")
    A(f"- Recall gate: {rec['strict_recall_at_primary_k_all']:.3f} → **{'PASS' if rec['passes_recall_gate'] else 'FAIL'}**")
    for mk in ("response_a", "response_b"):
        d = dec.get(mk)
        if isinstance(d, dict):
            A(f"- {disp[mk]}: quality {d['quality_diff_pp']:+.1f} pp vs full history, token reduction {d['token_reduction_pct']:.1f}%, retention {d['retention_pct']:.0f}% → **{d['verdict']}**" + (f" ({'; '.join(d['reasons'])})" if d["reasons"] else ""))
    A(f"\n**F0.5 verdict: {overall}.**\n")

    # ---- cost
    A("## Cost\n")
    A(f"Actual F0.5 spend: **${L.total:.2f}** across {L.calls:,} LLM calls ({L.tokens_in:,} input / {L.tokens_out:,} output tokens), against the plan's ≈ $12 estimate, $18 warning and $25 hard limit (never reached). F0's Opus reference verdicts were reused at zero cost.\n")
    A(md(pd.DataFrame([{"purpose": k, "usd": round(v, 2)} for k, v in sorted(L.by_purpose.items(), key=lambda kv: -kv[1])])))
    A(""); A(md(pd.DataFrame([{"model": k, "usd": round(v, 2)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])])))
    n_judged = sum(1 for _ in open(ROOT / "results" / "scored" / "scores.jsonl")) if (ROOT / "results" / "scored" / "scores.jsonl").exists() else 0
    if len(ad):
        A(f"\nFor comparison, judging the same instances with Opus 4.6 at F0's measured ≈ $0.017/call would have cost ≈ ${0.017 * n_judged:.0f}; the adopted judge cost ${L.by_purpose.get('judge', 0):.2f}.\n")
    else:
        cheapest = cal.sort_values("usd_per_call").iloc[0]
        A(f"\nThe cost-efficiency plan did not pay off in this phase: the Opus judge cost ${L.by_purpose.get('judge', 0):.2f} for the gating and exploratory arms, where the cheapest calibrated candidate ({cheapest.display}) would have cost ≈ ${cheapest.usd_per_call * n_judged:.2f}. "
          "The calibration itself cost under $1 and is reusable: the next phase can decide whether a κ-only bar, or a bar tied to Opus's own repeatability, is the right adoption rule.\n")

    # ---- recommendation
    A("## Recommendation\n")
    sem = attr[attr.source == "semantic"].iloc[0]
    if overall == "PASS":
        A(f"Per §12.2, F0.5 passes check 2: a cheap, non-LLM candidate generator puts the full gold parent set inside a {pk}-turn pool on {100 * rec['strict_recall_at_primary_k_all']:.1f}% of scenarios, and an oracle restricted to that pool keeps F0's token saving with quality within the non-inferiority margin. "
          "Proceed to check 3 (retrieval/compression comparability against the *candidate-realistic* oracle) and router scoping (R1.1), sized against these candidate-generation numbers rather than F0's oracle-optimistic ones.\n")
    else:
        A("Per §12.2 point 2, F0.5 does not pass check 2 on the frozen thresholds; candidate generation (or the restricted oracle's quality) is the next research problem, not an LLM router.\n")
    A("What the source breakdown says about where to invest next:\n")
    A(f"- Embedding similarity is doing almost all the work: it proposes {100 * sem.share_of_gold_turns:.1f}% of gold turns and is the *only* source for {int(sem.gold_turns_found_only_by_this_source)} of them; dropping it collapses uncapped strict recall to {abl[(abl.dropped_source == 'semantic') & (abl.k == 'uncapped')].strict_recall.iloc[0]:.3f}. Structural sources (branch chain, inactive heads, recency) are individually redundant at k ≥ 10.")
    A(f"- Small pools are the real constraint, not discovery: strict recall goes {rec['strict_recall_at_5_all']:.2f} → {by_k[(by_k.subset == 'all_145') & (by_k.k == '10')].strict_recall.iloc[0]:.2f} → {rec['strict_recall_at_primary_k_all']:.2f} from k=5 to 10 to {pk}. The ranking (sources, then cosine) places same-branch distractors that three sources agree on above gold turns that only similarity finds; a learned or cosine-first ranker is the cheapest next improvement.")
    A("- The only outright miss is `three_way_join_004` (two gold turns of a nine-turn closure never proposed): a long multi-branch join whose middle turns are neither branch heads, nor recent, nor lexically or semantically close to the query.")
    A("- Benchmark: F0.5's k=15 gate is weak on this benchmark because 111 of 145 histories fit inside the pool. A benchmark 1.2 with longer histories (30–60 turns) in the join and resume families would make Recall@k informative where a deployed system would actually be stressed.")
    A("\n## Assumptions and limitations\n")
    A("- Branch structure of *prior* turns comes from gold parents (perfect past routing). A deployed system's own routing errors would compound; F0.5 measures only the candidate step.")
    A("- The candidate oracle still uses the gold closure to pick from the pool; it bounds what a perfect selector could do from a cheap pool, and says nothing about an actual router's precision.")
    if adopted.get("adopted_judge"):
        A(f"- Quality is judged by {adopted.get('display')} rather than Opus 4.6; the calibration table and judge-shift table quantify the difference. Cross-vendor, and not a responder in this study.")
    else:
        A("- Quality is judged by Claude Opus 4.6, the same vendor family as two of the three responders (the self-preference concern flagged in F0 stands). The cheap cross-vendor judges were calibrated but not adopted; their verdicts on the 160-instance subsample are kept in `results/scored/calibration_scores.jsonl`.")
        routes = pd.Series([json.loads(l).get("judge_route", "global.anthropic.claude-opus-4-6-v1@us-east-1") for l in open(ROOT / "results" / "scored" / "scores.jsonl") if l.strip() and "copied_from" not in l]).value_counts()
        A("- Opus verdicts come from the same model via different inference profiles and regions: F0's baselines via the `us.` and `global.` profiles (F0's sharding); F0.5's own verdicts mostly via the `global.` profile in us-east-1, with the last ~35 routed through the `us.` profile and us-west-2 after the global profile's daily token quota stalled the run for nine hours. Region/profile fallback is now built into the client and every record carries its route. Routes used in F0.5: " + "; ".join(f"{k} ×{v}" for k, v in routes.items()) + ".")
    A("- 145 scenarios, most with short histories; recall CIs are correspondingly wide at small k and near-degenerate at k ≥ 15.")
    A("- MiniMax M2.5's Bedrock per-token rate was not confirmed from the console; the ledger bills it at $0.60 / $2.40 per 1M (top of the handoff's range).")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
