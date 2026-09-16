"""Bridge for the length ablation: own manifest/ledger via F05_ROOT; F0 + F0.5 modules on sys.path."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
os.environ["F05_ROOT"] = str(ROOT)
for p in (REPO / "f0-oracle-feasibility" / "src", REPO / "f05-candidate-realism" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

F0_SCENARIOS = REPO / "f0-oracle-feasibility" / "data" / "scenarios"
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


def instance_key(scenario_id: str, method: str, budget, model: str) -> str:
    return f"{scenario_id}|{method}|{budget if budget is not None else '-'}|{model}"
