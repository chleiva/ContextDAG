"""Read-only bridge to the F0 phase: puts F0's src on sys.path so schema / context_methods /
metrics are imported unchanged, and exposes F0's data and result paths.

F0's context_methods inserts its own directory at sys.path[0] on import, so every F0.5 module
uses a distinct name (f05_*) to avoid shadowing F0's cost.py / llm.py / analyze.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]                 # f05-candidate-realism/
REPO = ROOT.parent
F0_ROOT = (ROOT / yaml.safe_load((ROOT / "manifest.yaml").read_text())["run"]["f0_dir"]).resolve()
F0_SRC = F0_ROOT / "src"
if str(F0_SRC) not in sys.path:
    sys.path.insert(0, str(F0_SRC))

F0_SCENARIOS = F0_ROOT / "data" / "scenarios"
F0_ANSWERS = F0_ROOT / "results" / "raw" / "answers.jsonl"
F0_SCORES = F0_ROOT / "results" / "scored" / "scores.jsonl"
F0_SEMANTIC_CACHE = F0_ROOT / "results" / "raw" / "semantic_selection.json"


def load_manifest() -> dict:
    return yaml.safe_load((ROOT / "manifest.yaml").read_text())


def load_f0_manifest() -> dict:
    return yaml.safe_load((F0_ROOT / "manifest.yaml").read_text())


def load_scenarios():
    from schema import load_all  # noqa: E402  (F0 module)
    return load_all(F0_SCENARIOS)


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass    # a line still being written by a concurrent process
    return out


def f0_answers() -> dict[str, dict]:
    return {r["key"]: r for r in read_jsonl(F0_ANSWERS)}


def f0_scores() -> dict[str, dict]:
    """First Opus verdict per key (F0 analysis also keeps the first)."""
    out: dict[str, dict] = {}
    for r in read_jsonl(F0_SCORES):
        out.setdefault(r["key"], r)
    return out


def instance_key(scenario_id: str, method: str, budget, model: str) -> str:
    return f"{scenario_id}|{method}|{budget if budget is not None else '-'}|{model}"


def method_label(method: str, budget) -> str:
    if budget is None or (isinstance(budget, float) and budget != budget):   # None or NaN (pandas)
        return method
    return f"{method}@{int(budget)}"
