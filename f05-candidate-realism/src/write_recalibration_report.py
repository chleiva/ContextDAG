"""Fill claude/JUDGE_RECALIBRATION_RESULTS.md (Judge_Recalibration_Exten.md §6) from
results/tables/recalibration_summary.csv, recalibration_method_means.csv, judge_recalibration_decision.json
and the extension's own ledger."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("F05_LEDGER", "recalibration")
from f0_bridge import REPO, ROOT, load_manifest  # noqa: E402
from f05_cost import ledger  # noqa: E402

T = ROOT / "results" / "tables"
OUT = REPO / "claude" / "JUDGE_RECALIBRATION_RESULTS.md"


def md(df: pd.DataFrame, fmt: str = "{:.4f}") -> str:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "" if pd.isna(x) else fmt.format(x))
    cols = [str(c) for c in df.columns]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
                     + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |" for _, r in df.iterrows()])


def main() -> None:
    man = load_manifest()
    rc = man["judge_recalibration"]
    bar = rc["judge_adoption_bar_v2"]
    df = pd.read_csv(T / "recalibration_summary.csv")
    mm = pd.read_csv(T / "recalibration_method_means.csv", index_col=0)
    dec = json.loads((T / "judge_recalibration_decision.json").read_text())
    L = ledger()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    new = {c["id"]: c for c in rc["new_candidates"]}
    routes = {r.judge: r.routes for r in df.itertuples()}
    L_ = []
    A = L_.append
    A("# Judge Recalibration Extension — Results\n")
    A(f"Run date: {date.today().isoformat()}  ")
    A(f"Manifest: `f05-candidate-realism/manifest.yaml` (`judge_recalibration` section) at commit {commit}  ")
    A("Instances: 160 (reused from F0.5 `results/raw/calibration_sample.json`, no resampling); reference verdicts: Claude Opus 4.6, reused from F0.5 (zero new Opus calls)  ")
    A("New candidates scored: " + "; ".join(f"{c['display']} (`{c['id']}`, route {routes.get(c['id'], '?')}, temperature {'default/1, reasoning model' if c.get('temperature') is None else c['temperature']})" for c in rc["new_candidates"]) + "  ")
    A("Bar applied: `judge_adoption_bar_v2` (frozen in the manifest before any new scoring): item κ ≥ "
      f"{bar['item_kappa_min']}, method ranking preserved (tie band {bar['ranking_tie_band']}), and |candidate contrast − Opus contrast| ≤ {bar['contrast_error_max']} on every one of dag−full, dag−tree, dag−sliding, dag−semantic. Cheapest passer wins.\n")
    sj = dec.get("standing_judge_display")
    A(f"**Decision: {'standing judge = ' + sj if sj else 'no candidate passed bar v2'}.**\n")
    A("## Reference contrasts (Opus 4.6 on the 160-instance sample)\n")
    A(md(pd.DataFrame([{k: v for k, v in dec["reference_contrasts"].items()}])))
    A("\nThe handoff quoted dag−full = −0.084 from an earlier rounding of the same data; the frozen value is the one computed here.\n")
    A("## Per-candidate results\n")
    cols = ["display", "n", "item_kappa", "ranking_preserved", "err_dag_minus_full", "err_dag_minus_tree", "err_dag_minus_sliding", "err_dag_minus_semantic", "max_abs_contrast_err", "mean_abs_score_delta_v1", "usd_per_call", "PASS_v2"]
    A(md(df[cols].rename(columns={"display": "candidate", "mean_abs_score_delta_v1": "mean |Δ| (old bar, info)", "usd_per_call": "$/call"})))
    A("\nErrors are candidate contrast minus Opus contrast (signed); a candidate fails if any |error| > 0.02. Sorted by $/call. Item agreement, Spearman ρ of the method ranking, fallback-prompt uses and routes are in `f05-candidate-realism/results/tables/recalibration_summary.csv`.\n")
    A("### Sampling noise of the contrast errors (information, not part of the bar)\n")
    A("Each contrast error was bootstrapped over the 160 instances (2,000 resamples). The table gives the standard error of each error and how many of the four errors have a 95% CI excluding zero. With ~32 instances per method on this sample, an error's standard error is roughly 0.03–0.04, so the 0.02 bound sits below the resolution of the sample: a candidate whose true error is zero would still fail it about half the time on one of four contrasts. This is reported so the next decision is made with the noise floor in view; the bar itself was not changed.\n")
    A(md(df[["display", "se_dag_minus_full", "se_dag_minus_tree", "se_dag_minus_sliding", "se_dag_minus_semantic", "mean_err_se", "n_contrast_errs_ci_excludes_zero"]].rename(columns={"display": "candidate", "n_contrast_errs_ci_excludes_zero": "errors whose 95% CI excludes 0 (of 4)"}), "{:.3f}"))
    A("")
    A("## Method means on the sample, per judge\n")
    A(md(mm.reset_index().rename(columns={"index": "method"}), "{:.3f}"))
    A("\n## Decision\n")
    if sj:
        row = df[df.judge == dec["standing_judge"]].iloc[0]
        A(f"Standing judge selected: **{sj}** (`{dec['standing_judge']}`), the cheapest of the passers ({', '.join(dec['passers'])}) at ${row.usd_per_call:.4f}/call, κ = {row.item_kappa:.3f}, max contrast error {row.max_abs_contrast_err:.4f}. "
          "Under the F0.5 protocol (~1,300 judge calls per phase) this is roughly $" + f"{1300 * row.usd_per_call:.2f}" + " per phase, versus ≈ $23 for Opus 4.6.\n")
    else:
        best = df.sort_values("max_abs_contrast_err").iloc[0]
        A(f"No candidate passed. Closest: **{best.display}** with max contrast error {best.max_abs_contrast_err:.4f} (bound {bar['contrast_error_max']}), κ = {best.item_kappa:.3f}. "
          "Per the handoff, the bar is not adjusted here; widening the tolerance is a pre-registered-threshold change that needs explicit sign-off, and Opus is not the default fallback.\n")
    A("## Cost\n")
    A(f"Actual spend for this extension: **${L.total:.2f}** across {L.calls} calls ({L.tokens_in:,} input / {L.tokens_out:,} output tokens), against the handoff's under-$1 estimate and the $5 ledger hard limit. Zero new Opus calls.\n")
    A(md(pd.DataFrame([{"model": k, "usd": round(v, 3)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    A("\n## Deferred, as instructed\n")
    A("An Opus 4.6 self test–retest floor (~40 instances, ~$3) would show how well Opus agrees with itself on this rubric; candidates are being asked to agree with a single Opus pass. Not run under the no-new-Opus policy; available as future work with explicit sign-off.\n")
    A("## What this unblocks\n")
    if sj:
        A(f"{sj} is the judge for benchmark 1.2 and check 3 (both still separately scoped). Its verdicts are not interchangeable with Opus's at the instance level (κ ≈ {row.item_kappa:.2f}); they are interchangeable for the four method contrasts this study reports, which is what the bar tests.\n")
    else:
        A("Benchmark 1.2 and check 3 still need a judge decision: either sign off on a wider contrast tolerance (with the table above as evidence) or add candidates.\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L_) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
