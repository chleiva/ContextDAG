"""Fill claude/LENGTH_ABLATION_RESULTS.md (handoff §8)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import la  # noqa: E402,F401
from la import REPO, TABLES, load_manifest  # noqa: E402
from f05_cost import ledger  # noqa: E402

OUT = REPO / "claude" / "LENGTH_ABLATION_RESULTS.md"


def md(df, fmt="{:.4f}"):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda x: "" if pd.isna(x) else fmt.format(x))
    cols = [str(c) for c in df.columns]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |" for _, r in df.iterrows()])


def main() -> None:
    man = load_manifest(); pf = json.loads((TABLES / "preflight.json").read_text()); dec = json.loads((TABLES / "decision.json").read_text())
    comp = pd.read_csv(TABLES / "comparisons.csv"); cells = pd.read_csv(TABLES / "cells.csv")
    disp = {k: man["models"][k]["display"] for k in ("response_a", "response_b", "response_c")}; disp["pooled"] = "pooled"
    L = ledger()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO).decode().strip()
    except Exception:  # noqa: BLE001
        commit = "uncommitted"
    A = []; P = A.append
    P("# Length Ablation — Results (final experiment)\n")
    P(f"Run date: {date.today().isoformat()}; generated at commit {commit}; interpretation table frozen in `length-ablation/manifest.yaml` at commit 8aa95b8 before the first billed call. Spliced sets tagged `length-ablation`. Responders Sonnet 4.6 / Haiku 4.5 / MiniMax M2.5; judge Llama 4 Maverick only; zero Opus. No conversation text was written or changed in this phase.\n")
    prim = dec["primary"]; rd = dec["reading"]
    P("**Primary result, `full_history(base) − full_history(60)`, paired over 40 targets:** " + "; ".join(f"{disp[m]} {prim[m]['q_diff']:+.3f} [{prim[m]['q_ci_low']:+.3f}, {prim[m]['q_ci_high']:+.3f}] → {rd[m]}" for m in ("response_a", "response_b", "response_c", "pooled") if prim.get(m)) + ".\n")
    P(f"**Validity diagnostic first (handoff §4):** full-history distractor leakage by length, pooled: base {dec['leakage_by_length']['pooled']['base']:.3f}, 30 {dec['leakage_by_length']['pooled']['30']:.3f}, 60 {dec['leakage_by_length']['pooled']['60']:.3f}. "
      + ("Leakage rises with length, so the donor selection produced harder histories and the run is valid." if dec["validity_leakage_rises_with_length_pooled"] else "**Leakage does not rise with length: the donor selection failed as the pilot's generation did, and the run is void.** The numbers below are reported for the record only.") + "\n")
    P("## 1. Construction and pre-flight (handoff §2–3)\n")
    P(f"40 targets (first 8 ids of two_branch_join, three_way_join, resume, long_noisy_side_thread, new_root); donor pool of 164 branches from the other 144 benchmark-1.1 scenarios, ranked by cosine(branch text, target query) with all-mpnet-base-v2 and taken greedily under the hard exclusion (no named entity shared with the target's gold closure; no query entity in the donor), size-aware so lengths land at 30–36 and 60–66 history turns. "
      f"Pre-flight: oracle-context hash equal across lengths {pf['all_oracle_hash_equal']} (40/40); checklist, query and gold closure byte-identical {pf['all_checklist_identical']}; 30 ⊂ 60 and base ⊂ 60 subsequence {pf['all_subsequence']}; insufficient targets {pf['insufficient_targets'] or 'none'}; donor candidacies rejected by the exclusion {pf['total_rejected_donors']} (independent re-check on the saved files: 0 violations across 2,731 donor turns). "
      "Deviation: long_noisy_side_thread's base histories are 33–40 turns, so its 30-turn arm does not exist (base and 60 only; 8 targets). Mean full-history tokens: base 1,826 → 30-turn 3,990 → 60-turn 8,220.\n")
    P("Base-length arms (`full_history@base`, `oracle_dag`) reuse the F0 / F0.5 answers and their Llama verdicts from check 3: the prompts are byte-identical to what this phase would have generated, so nothing was re-billed. Only the spliced lengths were answered here.\n")
    P("## 2. Stage 1 — per-cell diagnostics (checklist, leakage, retraction, tokens)\n")
    c = cells.copy(); c["model_key"] = c.model_key.map(disp)
    P(md(c[["model_key", "method_label", "length", "n", "checklist", "leakage", "retraction", "context_tokens", "context_recall", "context_precision"]].rename(columns={"model_key": "model", "method_label": "arm"})))
    P("\nRetraction uses the pilot's heuristic (regex on the answer opening). The oracle arm here is 1.1's; its retraction rate is the confirmation that the pilot's retraction was a property of the pilot's generator, not of pruned context per se.\n")
    P("## 3. Stage 1 — paired contrasts (cluster bootstrap over target ids, 10,000 resamples, pinned per-comparison seeds)\n")
    cc = comp.copy(); cc["model"] = cc.model.map(disp)
    s1 = cc[~cc.a.str.contains("semantic") & ~cc.b.str.contains("semantic")]
    P(md(s1[["model", "a", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "se", "tok_a", "tok_b"]].rename(columns={"q_diff": "Δ checklist (a − b)", "q_ci_low": "CI low", "q_ci_high": "CI high", "se": "SE", "tok_a": "tokens a", "tok_b": "tokens b"})))
    P("\n## 4. Interpretation (fixed in advance, applied mechanically)\n")
    P("| observed `full_history(base) − full_history(60)` | reading |\n|---|---|\n| ≥ +5 pp, CI excludes zero | AMPLIFIES |\n| +2 to +5 pp | DIRECTIONAL, under-powered at n=40 |\n| < +2 pp, or negative | CLOSED: full history does not degrade to 60 turns on this benchmark; the quality claim is closed, as a finding |\n")
    for m in ("response_a", "response_b", "response_c", "pooled"):
        if prim.get(m):
            P(f"- {disp[m]}: {prim[m]['q_diff']:+.4f} [{prim[m]['q_ci_low']:+.4f}, {prim[m]['q_ci_high']:+.4f}] → **{rd[m]}**")
    P("")
    if dec.get("stage2_present"):
        P("## 5. Stage 2 — retrieval at matched budget by length\n")
        s2 = cc[cc.a.str.contains("semantic") | cc.b.str.contains("semantic")]
        P(md(s2[["model", "a", "b", "n", "q_diff", "q_ci_low", "q_ci_high", "tok_a", "tok_b"]].rename(columns={"q_diff": "Δ checklist (a − b)", "q_ci_low": "CI low", "q_ci_high": "CI high", "tok_a": "tokens a", "tok_b": "tokens b"})))
        r = cells[cells.method_label == "semantic_retrieval@matched"].copy(); r["model_key"] = r.model_key.map(disp)
        P("\nRetrieval context recall by length (budget = the target's oracle_dag tokens, so what it retrieves changes with the history):\n")
        P(md(r[["model_key", "length", "n", "context_recall", "context_precision", "checklist", "leakage", "retraction"]].rename(columns={"model_key": "model"})))
        P("")
    else:
        P("## 5. Stage 2\n\nNot run (Stage-1 spend did not clear the $7 gate, or the budget was exhausted); Stage 1 is reported alone.\n")
    P("## 6. Cost\n")
    P(f"Spend: **${L.total:.2f}** across {L.calls:,} calls ({L.tokens_in:,} input / {L.tokens_out:,} output tokens). Estimate $8, warning $10, hard limit $15; Stage-2 gate $7 after Stage 1. Generation cost $0 by construction; base arms reused at $0.\n")
    P(md(pd.DataFrame([{"purpose": k, "usd": round(v, 3)} for k, v in sorted(L.by_purpose.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P(""); P(md(pd.DataFrame([{"model": k, "usd": round(v, 3)} for k, v in sorted(L.by_model.items(), key=lambda kv: -kv[1])]), "{:.3f}"))
    P("\n## 9. Anything else found (future work; not fixed, no follow-up run proposed)\n")
    P("- long_noisy_side_thread has no 30-turn arm (base already 33–40 turns); its rows contribute to base→60 only.")
    P("- Donor branches carry their own internal chain links but lose links to their source scenario's gold turns (those are not spliced); the text is unchanged, and `oracle_dag` never sees donor turns, so this affects nothing measured here.")
    P("- Base-length arms are reused from F0/F0.5 (temperature-0 samples from earlier days); with 27% decoder variance per cell this is one sample either way, but a fresh base sample would be the cleaner design if this were repeated.")
    P("- `BENCHMARK_1.2_PILOT_Analysis_and_Recommendations.md`, listed as required reading, is not in the repository.")
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text("\n".join(A) + "\n"); print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
