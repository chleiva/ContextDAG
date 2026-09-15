"""Bridge for the benchmark 1.2 pilot: points the shared F0.5 client/ledger at this directory
(F05_ROOT) and puts F0's and F0.5's src on sys.path. Import this first in every pilot script."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
os.environ["F05_ROOT"] = str(ROOT)          # f05_cost / f05_llm read manifest + ledger from here
for p in (REPO / "f0-oracle-feasibility" / "src", REPO / "f05-candidate-realism" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SCENARIOS = ROOT / "data" / "scenarios"
META = ROOT / "data" / "meta"
RAW = ROOT / "results" / "raw"
SCORED = ROOT / "results" / "scored"
TABLES = ROOT / "results" / "tables"


def load_manifest() -> dict:
    return yaml.safe_load((ROOT / "manifest.yaml").read_text())


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def load_scenarios():
    from schema import load_all  # noqa: E402
    return load_all(SCENARIOS)


def instance_key(scenario_id: str, method: str, budget, model: str) -> str:
    return f"{scenario_id}|{method}|{budget if budget is not None else '-'}|{model}"
