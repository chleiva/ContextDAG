"""Handoff §3 stop rule, evaluated on FIRST attempts (the generator regenerates failures with feedback,
so the final set passes by construction; the first-attempt rate is the honest instrument reading)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot  # noqa
from pilot import META, RAW, load_manifest
thr = load_manifest()["generation"]["cosine_gate"]["stop_if_first_attempt_pass_rate_below"]
accepted = {p.stem for p in META.glob("*.json")}
first = {}
for line in (RAW / "cosine_gate_attempts.jsonl").read_text().splitlines():
    r = json.loads(line)
    if r["scenario_id"] in accepted and r["scenario_id"] not in first:
        first[r["scenario_id"]] = r
rates = [bool(r["pass"]) for r in first.values() if r.get("gold_median") is not None]
rate = sum(rates) / len(rates) if rates else float("nan")
final = sum(1 for sid in accepted if json.loads((META / f"{sid}.json").read_text())["cosine"]["pass"]) / max(len(accepted), 1)
print(f"accepted scenarios {len(accepted)}; first-attempt cosine gate pass rate {rate:.2f} (n={len(rates)}, new_root excluded: no gold); final-set pass rate {final:.2f}; stop threshold {thr}")
if rate < thr:
    print("STOP_BEFORE_ANSWERS: first-attempt pass rate below threshold (handoff §3)"); sys.exit(3)
