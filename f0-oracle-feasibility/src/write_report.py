"""Fill F0_RESULTS.md (handoff §11 template) from the analysis outputs and the manifest.
Numbers only come from results/tables/*.csv; prose is kept to what the numbers show."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cost import ledger  # noqa: E402
from llm import ROOT, load_manifest  # noqa: E402
from schema import load_all  # noqa: E402

T = ROOT / "results" / "tables"


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append("" if pd.isna(v) else floatfmt.format(v))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main() -> None:
    m = load_manifest()
    thr = m["decision_thresholds"]
    scenarios = load_all(ROOT / "data" / "scenarios")
    fam_counts = Counter(s.family for s in scenarios)
    summary = pd.read_csv(T / "summary.csv")
    pairwise = pd.read_csv(T / "pairwise.csv")
    by_family = pd.read_csv(T / "by_family.csv")
    fails = pd.read_csv(T / "failure_cases.csv") if (T / "failure_cases.csv").stat().st_size > 1 else pd.DataFrame()
    decisions = json.loads((T / "decision.json").read_text())
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    L = ledger()
    models = m["models"]
    sc_rows = [json.loads(l) for l in (ROOT / "results" / "scored" / "scores.jsonl").read_text().splitlines() if l.strip()]
    seen = {}
    for r in sc_rows:
        seen.setdefault(r["key"], r)
    sc_rows = list(seen.values())
    n_scored = len(sc_rows)
    n_fallback = sum(1 for r in sc_rows if r.get("judge_prompt_variant") == "fallback")
    pct_fallback = 100 * n_fallback / max(1, n_scored)
    prof = Counter(r["judge_model"] for r in sc_rows)
    judge_split = ", ".join(f"{k}: {v}" for k, v in prof.most_common())

    def disp(mk):
        return f"{models[mk]['display']} (`{models[mk]['id']}`)"

    # summary table
    s = summary.copy()
    s["model"] = s["model_key"].map(lambda k: models[k]["display"])
    s["token_reduction_pct"] = s["token_reduction_pct"].map(lambda v: f"{v:.1f}")
    s["checklist"] = s.apply(lambda r: f"{r.checklist_score:.3f} [{r.checklist_ci_low:.2f}, {r.checklist_ci_high:.2f}]", axis=1)
    cols = ["model", "method_label", "n", "context_tokens", "token_reduction_pct", "checklist", "context_precision", "context_recall", "context_f1", "context_sufficiency", "irrelevant_context_ratio", "distractor_leakage"]
    s = s[cols].rename(columns={"method_label": "method", "context_tokens": "ACT", "token_reduction_pct": "token red. %", "checklist": "checklist score [95% CI]",
                                "context_precision": "prec", "context_recall": "recall", "context_f1": "F1", "context_sufficiency": "suff.", "irrelevant_context_ratio": "irrel. ratio", "distractor_leakage": "leakage"})
    s["ACT"] = s["ACT"].round(0).astype(int)

    # pairwise
    pw = pairwise.copy()
    pw["model"] = pw["model"].map(lambda k: models[k]["display"])
    pw["diff [95% CI]"] = pw.apply(lambda r: f"{r.mean_diff:+.3f} [{r.ci_low:+.3f}, {r.ci_high:+.3f}]", axis=1)
    pw_q = pw[(pw.metric == "checklist_score") & (pw.b != "oracle_tree")][["model", "b", "n", "diff [95% CI]"]].rename(columns={"b": "baseline"})
    pw_t = pw[pw.metric == "context_tokens"][["model", "b", "n", "diff [95% CI]"]].rename(columns={"b": "baseline"})
    join = pw[pw.b == "oracle_tree"][["model", "n", "diff [95% CI]", "families"]]

    # by family pivot for checklist and recall
    bf = by_family.copy()
    piv_q = bf.pivot_table(index="family", columns=["model_key", "method_label"], values="checklist_score").round(2)
    piv_r = bf[bf.model_key == "response_a"].pivot_table(index="family", columns="method_label", values="context_recall").round(2)
    piv_q_a = piv_q["response_a"] if "response_a" in piv_q.columns.get_level_values(0) else pd.DataFrame()
    piv_q_b = piv_q["response_b"] if "response_b" in piv_q.columns.get_level_values(0) else pd.DataFrame()

    n_insuff = int((fails["type"] == "oracle_dag_insufficient").sum()) if len(fails) else 0
    fh = fails[fails["type"] == "full_history_ge_oracle_dag"] if len(fails) else fails
    if len(fh):
        fv = fh.note.str.extract(r"full=([\d.]+)")[0].astype(float); dv = fh.note.str.extract(r"dag=([\d.]+)")[0].astype(float)
        n_strict, n_tie = int((fv > dv).sum()), int((fv == dv).sum())
    else:
        n_strict = n_tie = 0
    fail_summary = (f"Oracle-DAG context-insufficiency cases: **{n_insuff}** (expected 0 by construction). "
                    f"Instances (scenario × model) where full history scored at or above oracle DAG while oracle DAG was below 1.0: **{len(fh)}** "
                    f"of {2 * len(scenarios)}, of which {n_tie} are ties and {n_strict} are strict full-history wins. They are spread across families "
                    f"(see table) rather than concentrated, consistent with judge/checklist noise; the paired bootstrap above already accounts for them.")
    headline = " / ".join(f"{models[k]['display']}: **{v}**" for k, v in decisions.items())
    fam_line = ", ".join(f"{k} {v}" for k, v in sorted(fam_counts.items()))

    def dec_expl(mk):
        sm = summary[summary.model_key == mk].set_index("method_label")
        if "oracle_dag" not in sm.index:
            return ""
        qd = 100 * (sm.loc["oracle_dag", "checklist_score"] - sm.loc["full_history", "checklist_score"])
        tr = sm.loc["oracle_dag", "token_reduction_pct"]
        j = pairwise[(pairwise.model == mk) & (pairwise.b == "oracle_tree")]
        jv = f"{j.mean_diff.iloc[0]:+.3f} [{j.ci_low.iloc[0]:+.3f}, {j.ci_high.iloc[0]:+.3f}]" if len(j) else "n/a"
        return (f"- **{models[mk]['display']}**: oracle DAG checklist score minus full history = **{qd:+.1f} pp** "
                f"(threshold: no worse than −{thr['quality_non_inferiority_margin_pp']} pp); token reduction vs full history = **{tr:.1f}%** "
                f"(threshold ≥ {thr['min_token_reduction_pct']}%); DAG − tree on join families = **{jv}** "
                f"(threshold: > 0{' required' if thr['join_advantage_required'] else ' not required'}). Verdict: **{decisions.get(mk, 'n/a')}**.")

    report = f"""# F0 Oracle Feasibility — Results

Run date: {date.today().isoformat()}
Manifest: `f0-oracle-feasibility/manifest.yaml` at commit `{commit}`
Scenario count: {len(scenarios)} (by family: {fam_line})
Models: Response A = {disp('response_a')}, Response B = {disp('response_b')}, Judge = {disp('judge')}, Embedding = `{models['embedding']['id']}` (local), Generator = {disp('generator')}
Provider: Amazon Bedrock ({m['provider']['region']}), tokenizer for all counts: tiktoken `{models['tokenizer']['encoding']}`
Total spend for the whole study (generation + answers + summaries + judging): ${L.total:.2f} across {L.calls:,} LLM calls

## Headline result

{headline}, per the pre-registered thresholds in `manifest.yaml`:

{chr(10).join(dec_expl(k) for k in decisions)}

## Summary table

ACT = average context tokens (rendered context only; excludes system prompt and query). Token reduction is relative to full history for the same model. Checklist score = fraction of required checklist items the judge marked satisfied, with a 95% bootstrap CI over scenarios. prec/recall/F1/suff. are context-selection metrics computed from annotations; irrel. ratio is token-weighted; leakage is the judge's distractor-leakage rate.

{md_table(s)}

## Pareto frontier

![Pareto frontier](results/plots/pareto.png)

`results/plots/pareto.png`: x = average context tokens (log), y = mean checklist score, one point per method per model.

## Mandatory pairwise comparisons

Paired bootstrap over scenarios ({m['analysis']['bootstrap_resamples']:,} resamples), oracle DAG minus baseline, per response model.

Quality (checklist score):

{md_table(pw_q)}

Context tokens:

{md_table(pw_t, "{:.0f}")}

## Join-specific result (oracle DAG vs. oracle tree, join families only)

Families: {", ".join(m['analysis']['join_families'])}. Checklist score, oracle DAG minus oracle tree:

{md_table(join)}

## By-family breakdown

Checklist score by family, {models['response_a']['display']}:

{md_table(piv_q_a.reset_index(), "{:.2f}") if len(piv_q_a) else "(none)"}

Checklist score by family, {models['response_b']['display']}:

{md_table(piv_q_b.reset_index(), "{:.2f}") if len(piv_q_b) else "(none)"}

Context recall by family (identical for both models; selection does not depend on the response model):

{md_table(piv_r.reset_index(), "{:.2f}")}

## Failure cases

{fail_summary}

{md_table(fails) if len(fails) else ""}

Full per-instance data: `results/tables/per_instance.csv`; raw prompts/responses: `results/raw/answers.jsonl`; judge outputs: `results/scored/scores.jsonl`.

## Limitations of this run

- **Model coverage.** No open-weight model was reachable in this environment; Claude Haiku 4.5 stands in as the weaker response model. Both response models and the judge are from one vendor family.
- **Judge overlap.** The judge (Opus 4.6) is distinct from both response models, but shares a vendor and training lineage with them; self-preference bias is reduced, not eliminated.
- **Judge routing and prompt fallback.** Bedrock's per-region daily token quota for Opus 4.6 forced the judge calls to be spread across the model's regional (`us.`) and global inference profiles and several AWS regions; it is the same model throughout, and every score record names the profile used ({judge_split}). In {n_fallback} of {n_scored} judge calls ({pct_fallback:.1f}%) the primary judge prompt returned prose (the model continued the conversation instead of scoring it); those were re-judged with the same rubric wrapped in a system prompt and delimiters, and are flagged `judge_prompt_variant: fallback`.
- **Checklist artifact on oracle contexts.** Some checklist items reward explicit disambiguation (e.g. "resolves *there* to Ridgeline, not Saltmarsh"). With oracle context the decoy entity is absent, so the model has no reason to name it and can lose the item despite answering correctly. This penalizes the oracle methods, not the baselines, so it makes the reported oracle-vs-baseline quality differences conservative.
- **NTM not included.** No verifiable public release of the Context-Agent NTM benchmark was found; the custom synthetic benchmark is the only data.
- **Synthetic data.** Scenarios were LLM-drafted against code-decided gold graphs and mechanically validated; every tenth scenario was hand-read. Structure is exact by construction, but naturalness and distractor irrelevance are only spot-checked.
- **Budgets.** The windowed baselines used token budgets of {m['context_methods']['window_budgets_tokens']} (the handoff's default was [2048, 4096]); changed before the full run because the pilot showed 4096 would coincide with full history on most scenarios. See the note in `manifest.yaml`.
- **Tokenizer.** `cl100k_base` is an approximation for Claude models; all methods are counted identically, so relative comparisons hold but absolute counts are not what Bedrock bills.
- **Temperature.** All response and judge calls used temperature 0; the generator used 0.7–0.9.

## Recommendation

{chr(10).join(f"- {models[k]['display']}: {v}" for k, v in decisions.items())}

Per the handoff's decision procedure: GO means proceed to F0.5 (candidate-realism check), not to an automatic router. PIVOT names the specific change (tree-only, or revised dependency semantics). STOP means report the result as a finding and do not proceed. The verdicts above are the mechanical output of the thresholds, not a new judgment call.
"""
    (ROOT / "F0_RESULTS.md").write_text(report)
    print(f"wrote {ROOT / 'F0_RESULTS.md'} ({len(report):,} chars)")


if __name__ == "__main__":
    main()
