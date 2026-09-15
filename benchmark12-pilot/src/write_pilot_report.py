"""Fill claude/BENCHMARK_1.2_PILOT_RESULTS.md (handoff §6)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot  # noqa: E402,F401
from pilot import RAW, REPO, ROOT, TABLES, load_manifest, read_jsonl  # noqa: E402
from f05_cost import ledger  # noqa: E402

OUT = REPO / "claude" / "BENCHMARK_1.2_PILOT_RESULTS.md"


def md(df: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "" if pd.isna(x) else fmt.format(x))
    cols = [str(c) for c in df.columns]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |" for _, r in df.iterrows()])


def main(extra_notes: list[str] | None = None) -> None:
    man = load_manifest(); g = json.loads((TABLES / "gate.json").read_text())
    comp = pd.read_csv(TABLES / "comparisons.csv"); arms = pd.read_csv(TABLES / "arms.csv")
    val = pd.read_csv(TABLES / "validation.csv"); vfam = pd.read_csv(TABLES / "validation_by_family.csv")
    disp = {k: man["models"][k]["display"] for k in ("response_a", "response_b", "response_c")}; disp["pooled"] = "pooled"
    L = ledger()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    gen = read_jsonl(RAW / "generation.jsonl")
    A = []; P = A.append
    P("# Benchmark 1.2 — Stage A (Length Pilot): Results\n")
    P(f"Run date: {date.today().isoformat()}; generated at commit {commit}. Gate frozen in `benchmark12-pilot/manifest.yaml` (`benchmark12_pilot`) at commit 863788c, before the first billed call. "
      "Scenarios: 40 long (8 × five families), ids `long_<family>_NNN`, `benchmark_version: 1.2-pilot`, `length_class: long`; benchmark 1.1 untouched. Generator: Claude Sonnet 4.6 (user's choice B). Responders: Sonnet 4.6, Haiku 4.5, MiniMax M2.5. Judge: Llama 4 Maverick only; zero Opus calls.\n")
    est = g["point_estimates"]
    P(f"**Gate verdict: {g['verdict']}.** `oracle_dag − full_history` point estimates: " + ", ".join(f"{disp[k]} {v:+.3f}" for k, v in est.items() if v is not None) + f"; pooled {g['pooled']['q_diff']:+.3f} [{g['pooled']['q_ci_low']:+.3f}, {g['pooled']['q_ci_high']:+.3f}]. "
      f"Thresholds: AMPLIFIES ≥ {g['thresholds']['amplifies_pp']} on ≥ {g['thresholds']['models_required']} of 3 models; PARTIAL {g['thresholds']['partial_low_pp']}–{g['thresholds']['amplifies_pp']} on ≥ 2; FLAT < {g['thresholds']['partial_low_pp']} on ≥ 2; otherwise awkward.\n")
    P("**Honest limitation (handoff §1):** at n=40 the standard error on the effect is ≈ 0.03 per model, so this pilot resolves the effect to roughly ±6 pp. It is a scoping instrument, not evidence; the verdict is on point estimates with the CI alongside.\n")
    P("## 1. Primary measurement: oracle_dag − full_history (paired, cluster bootstrap over scenario ids, 10,000 resamples, pinned per-comparison seeds)\n")
    pm = comp[(comp.a == "oracle_dag") & (comp.b == "full_history")].copy(); pm["model"] = pm.model.map(disp)
    P(md(pm[["model", "n", "q_diff", "q_ci_low", "q_ci_high", "se", "tok_ratio"]].rename(columns={"q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "se": "SE", "tok_ratio": "tokens dag/full"}), "{:.4f}"))
    P("\nFor comparison, benchmark 1.1 (nine-turn histories, Opus judge) gave +0.026 (Sonnet), +0.026 (Haiku), +0.023 (MiniMax) on the same contrast; F0.5's small-closure subset gave +0.041 / +0.095 (Sonnet / Haiku).\n")
    P("## 2. Also reported (handoff §5)\n")
    P("### oracle_dag − semantic_retrieval@matched (does the matched-budget result hold at 45 turns?)\n")
    sm = comp[(comp.a == "oracle_dag") & (comp.b == "semantic_retrieval@matched")].copy(); sm["model"] = sm.model.map(disp)
    P(md(sm[["model", "n", "q_diff", "q_ci_low", "q_ci_high", "tok_ratio"]].rename(columns={"q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "tok_ratio": "tokens dag/matched"}), "{:.4f}"))
    P("\nOther exploratory contrasts:\n")
    ot = comp[~((comp.a == "oracle_dag") & comp.b.isin(["full_history", "semantic_retrieval@matched"]))].copy(); ot["model"] = ot.model.map(disp)
    P(md(ot[["model", "a", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "tok_ratio"]].rename(columns={"q_diff": "Δ checklist", "q_ci_low": "CI low", "q_ci_high": "CI high", "tok_ratio": "tokens a/b"}), "{:.4f}"))
    P("\n### Per-arm: tokens, precision, irrelevant-context ratio, distractor leakage, checklist (Llama)\n")
    ar = arms.copy(); ar["model"] = ar.model.map(disp)
    P(md(ar[["model", "arm", "n", "context_tokens", "token_ratio_vs_full", "context_precision", "context_recall", "irrelevant_context_ratio", "distractor_leakage", "checklist", "q_ci_low", "q_ci_high", "output_tokens"]].rename(columns={"context_tokens": "tokens", "token_ratio_vs_full": "ratio vs full", "context_precision": "precision", "context_recall": "recall", "irrelevant_context_ratio": "irrelevant ratio", "distractor_leakage": "leakage", "q_ci_low": "CI low", "q_ci_high": "CI high"})))
    P("\n## 3. Validation (handoff §3, §3.1)\n")
    P(f"Cosine gate (all-mpnet-base-v2; median distractor cosine ≥ 0.60 × median gold cosine): **first-attempt pass rate {100 * g['cosine_gate_first_attempt_pass_rate']:.0f}%** (the honest instrument reading; failures were regenerated with the reasons fed back), final-set pass rate {100 * g['cosine_gate_final_pass_rate']:.0f}%. "
      f"Closure/history ratio median {g['closure_ratio_median']:.2f} (target ≤ 0.35). Generation attempts logged: {len(gen)} calls for 40 accepted scenarios.\n")
    P(md(vfam.rename(columns={"history": "history turns", "tokens": "full-history tokens", "closure_ratio_median": "closure ratio (median)", "cosine_ratio_median": "cosine ratio (median)", "gate_pass_final": "gate pass (final)", "gate_pass_first": "gate pass (1st attempt)", "attempts_mean": "attempts"})))
    P("\nPer scenario (`benchmark12-pilot/results/tables/validation.csv`): history length, tokens, closure ratio, first-attempt and final cosine ratio, attempts, registry size, near-miss turn.\n")
    P("Assertions applied at generation (all must pass for admission): every distractor branch mentions ≥ 2 registry entities; one designated near-miss turn; no thin turns; ≥ 4,000 full-history tokens; every required checklist item cites evidence turns inside the gold closure (satisfiability); join families' required items span ≥ 2 gold branches (discrimination); 1.1's signposting ban. Rejection reasons per attempt are in `results/raw/generation.jsonl` and `results/raw/cosine_gate_attempts.jsonl`.\n")
    P("## 4. What Stage B should be\n")
    v = g["verdict"]
    if v == "AMPLIFIES":
        P("Per the frozen gate: generate to ≈ 130 long scenarios total (same generator and assertions, add compound_turn first-request, ambiguous_reference and semantic_decoy) and pursue the superiority claim with the full retrieval budget sweep under a criterion whose FAIL branch is reachable.\n")
    elif v == "PARTIAL":
        P("Per the frozen gate: stop and report. ≈ 200 long scenarios would be needed to power the claim; that is a budget decision for Christian, not for this session.\n")
    elif v == "FLAT":
        P("Per the frozen gate: stop; generate nothing further now. No powered quality claim is reachable at feasible n. Benchmark 1.2 becomes ≈ 60–80 long scenarios whose purpose is to make the efficiency and leakage claims visible at realistic length, and the paper is an efficiency-and-leakage paper. Recorded as a finding, not a failure.\n")
    else:
        P("The result is awkward under the frozen gate (see the per-model estimates): reported as awkward, no interpretation, no further generation.\n")
    P("## 5. Cost\n")
    P(f"Pilot spend: **${L.total:.2f}** across {L.calls:,} calls ({L.tokens_in:,} input / {L.tokens_out:,} output tokens); estimate $20, warning $35, hard limit $50. Zero Opus.\n")
    P(md(pd.DataFrame([{"purpose": k, "usd": round(v, 3)} for k, v in sorted(L.by_purpose.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P(""); P(md(pd.DataFrame([{"model": k, "usd": round(v, 3)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P("\n## 6. Limitations\n")
    P("- n=40, SE ≈ 0.03 per model; verdict on point estimates by design.")
    P("- Judge is Llama 4 Maverick (calibrated against Opus on 1.1's method contrasts, not on long histories); its prompt includes every distractor turn, so long scenarios put 5–8k tokens in front of the judge.")
    P("- Distractor realism is asserted by entity reuse, same-premise construction, a near-miss slot and the cosine gate; the gate's first-attempt pass rate is the honest measure of how often the writer produced separable filler unprompted.")
    P("- The 1.1 defect `three_way_join_003` (one checklist item unsatisfiable from any context) is not retro-patched; the satisfiability assertion prevents it here.")
    P("- Temperature-0 decoder noise (27% of per-scenario variance on 1.1) applies here too; one sample per cell.")
    P("\n## 8. Anything else found\n")
    for n in (extra_notes or ["- (none beyond the limitations above)"]):
        P(n)
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text("\n".join(A) + "\n"); print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
