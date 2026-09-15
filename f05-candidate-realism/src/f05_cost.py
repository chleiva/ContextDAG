"""F0.5 spend ledger and guardrail (same design as F0's cost.py, separate ledger file).

Every successful LLM call is appended to results/raw/cost_ledger.jsonl with actual token
usage and price. check_budget() refuses to proceed once the hard limit in manifest.yaml is
reached and warns once past the warning threshold.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import yaml

import os

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "results" / "raw" / "cost_ledger.jsonl"
# The judge-recalibration extension keeps its own ledger and budget (manifest: judge_recalibration).
# Select it with F05_LEDGER=recalibration in the environment.
_LEDGER_SCOPE = os.environ.get("F05_LEDGER", "")
if _LEDGER_SCOPE == "recalibration":
    LEDGER = ROOT / "results" / "raw" / "cost_ledger_recalibration.jsonl"
elif _LEDGER_SCOPE == "check3":
    LEDGER = ROOT / "results" / "raw" / "cost_ledger_check3.jsonl"


class BudgetExceeded(RuntimeError):
    pass


def _manifest() -> dict:
    return yaml.safe_load((ROOT / "manifest.yaml").read_text())


def price(model: str, input_tokens: int, output_tokens: int, manifest: dict | None = None) -> float:
    m = manifest or _manifest()
    table = m["pricing_usd_per_1m_tokens"]
    if model not in table:
        # global.<id> and us.<id> are the same model at the same list price; accept either spelling
        alt = ("us." + model[7:]) if model.startswith("global.") else (("global." + model[3:]) if model.startswith("us.") else None)
        if alt in table:
            model = alt
        else:
            raise KeyError(f"no price for model {model!r} in manifest.yaml; add it before calling")
    p = table[model]
    return input_tokens / 1e6 * p["input"] + output_tokens / 1e6 * p["output"]


class Ledger:
    def __init__(self) -> None:
        self.manifest = _manifest()
        self.total = 0.0
        self.by_model: dict[str, float] = defaultdict(float)
        self.by_purpose: dict[str, float] = defaultdict(float)
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._warned = False
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not LEDGER.exists():
            return
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                self._add(json.loads(line))

    def _add(self, rec: dict) -> None:
        self.total += rec["usd"]
        self.by_model[rec["model"]] += rec["usd"]
        self.by_purpose[rec.get("purpose", "?")] += rec["usd"]
        self.calls += 1
        self.tokens_in += rec["input_tokens"]
        self.tokens_out += rec["output_tokens"]

    def _budget(self) -> dict:
        if _LEDGER_SCOPE == "recalibration":
            return self.manifest["judge_recalibration"]["budget"]
        if _LEDGER_SCOPE == "check3":
            return self.manifest["check3"]["budget"]
        return self.manifest["budget"]

    def check_budget(self) -> None:
        b = self._budget()
        if self.total >= b["hard_limit_usd"]:
            raise BudgetExceeded(f"cumulative F0.5 spend ${self.total:.2f} has reached the hard limit ${b['hard_limit_usd']:.2f}; refusing further LLM calls")
        if self.total >= b["warn_usd"] and not self._warned:
            self._warned = True
            print(f"\n*** BUDGET WARNING: cumulative F0.5 spend ${self.total:.2f} has passed ${b['warn_usd']:.2f}; "
                  f"hard stop at ${b['hard_limit_usd']:.2f} ***\n", file=sys.stderr, flush=True)

    def record(self, model: str, input_tokens: int, output_tokens: int, purpose: str, ref: str = "") -> float:
        usd = price(model, input_tokens, output_tokens, self.manifest)
        with self._lock:
            rec = {"ts": time.time(), "model": model, "purpose": purpose, "ref": ref,
                   "input_tokens": input_tokens, "output_tokens": output_tokens, "usd": round(usd, 6)}
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with LEDGER.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            self._add(rec)
        return usd

    def report(self) -> str:
        b = self._budget()
        lines = [f"{_LEDGER_SCOPE.capitalize() if _LEDGER_SCOPE else 'F0.5'} spend: ${self.total:.2f} of ${b['hard_limit_usd']:.2f} hard limit (estimate ${b['estimate_usd']:.2f}, warn ${b['warn_usd']:.2f})",
                 f"calls: {self.calls}, tokens in: {self.tokens_in:,}, out: {self.tokens_out:,}"]
        for k, v in sorted(self.by_purpose.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {k:16s} ${v:7.2f}")
        for k, v in sorted(self.by_model.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {k:48s} ${v:7.2f}")
        return "\n".join(lines)


_ledger: Ledger | None = None


def ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger()
    return _ledger


if __name__ == "__main__":
    print(ledger().report())
