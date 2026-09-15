"""Data model for F0 scenarios (handoff §2) and the validation checklist (§3.3)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

FAMILIES = [
    "continuation", "topic_fork", "resume", "new_root", "two_branch_join",
    "three_way_join", "semantic_decoy", "constraint_retention", "knowledge_update",
    "ambiguous_reference", "long_noisy_side_thread", "join_then_split", "compound_turn",
]
# Families where a plausible wrong-branch answer exists, so a negative checklist item is required.
NEGATIVE_CHECK_REQUIRED = [f for f in FAMILIES if f not in ("continuation", "new_root")]

# Topic-switch signposting that leaks the conversation's structure lexically (handoff §3.2
# step 3 forbids it). Checked on user messages; any hit is a validation error so the
# generator retries.
SIGNPOST_PATTERNS = [
    r"\bon a (completely |totally |slightly )?(different|separate|unrelated) (note|topic|subject|matter)\b",
    r"\bseparately\b", r"\bunrelated(ly)?\b", r"\bswitching (topics|gears|subjects)\b", r"\bchanging (the )?(topic|subject)\b",
    r"\b(going|coming|getting|circling|jumping|moving) back to\b", r"\bback to (the|our|my)\b", r"\bback on (the|our|my)\b",
    r"\bas a separate (matter|question|thing)\b", r"\bone more (thing|question)\b", r"\bwhile (I|we)('re| are) at it\b",
    r"\bdifferent question\b", r"\bnew topic\b", r"\bside note\b", r"\bmeanwhile\b",
]
_SIGNPOST_RE = re.compile("|".join(SIGNPOST_PATTERNS), re.IGNORECASE)


def find_signposting(text: str) -> list[str]:
    return [m.group(0) for m in _SIGNPOST_RE.finditer(text)]


class Turn(BaseModel):
    turn_id: str
    turn_index: int
    user_message: str
    assistant_message: Optional[str]
    gold_parents: list[str] = Field(default_factory=list)
    stale: bool = False
    superseded_by: Optional[str] = None


class ChecklistItem(BaseModel):
    id: str
    criterion: str
    required: bool = True


class Scenario(BaseModel):
    scenario_id: str
    family: str
    label: str
    turns: list[Turn]
    evidence_turn_ids: list[str]
    distractor_turn_ids: list[str]
    answer_checklist: list[ChecklistItem]
    notes: str = ""
    # Set by the generator when evidence_turn_ids intentionally differs from the ancestor
    # closure (handoff §2.2); the validator then reports it as "reviewed" instead of "flagged".
    evidence_note: Optional[str] = None
    premise: Optional[str] = None
    # Benchmark 1.1: for turns whose user message bundles two requests, which part the query
    # actually depends on. Keys are turn_ids in evidence_turn_ids; values describe the part
    # (e.g. "first_request", "second_request"). Context methods stay turn-level; this lets a
    # later phase measure the sub-turn granularity cost.
    evidence_spans: Optional[dict[str, str]] = None
    benchmark_version: str = "1.0"
    length_class: Optional[str] = None      # benchmark 1.2: "long" for 30-60 turn histories; None for 1.1 scenarios

    # ---- helpers ----
    def turns_by_id(self) -> dict[str, Turn]:
        return {t.turn_id: t for t in self.turns}

    @property
    def query(self) -> Turn:
        return self.turns[-1]

    @property
    def history(self) -> list[Turn]:
        return self.turns[:-1]


def ancestors(query_turn_id: str, turns_by_id: dict[str, Turn], use_primary_only: bool = False) -> set[str]:
    """Ancestor closure per handoff §5.1. Does NOT include query_turn_id itself."""
    visited: set[str] = set()
    stack = [query_turn_id]
    while stack:
        tid = stack.pop()
        parents = turns_by_id[tid].gold_parents
        if use_primary_only and len(parents) > 1:
            parents = parents[:1]
        for p in parents:
            if p not in visited:
                visited.add(p)
                stack.append(p)
    return visited


class ValidationResult(BaseModel):
    scenario_id: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    closure_matches_evidence: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_scenario(s: Scenario) -> ValidationResult:
    """Every check from handoff §3.3 that can be done mechanically."""
    r = ValidationResult(scenario_id=s.scenario_id)
    err, warn = r.errors.append, r.warnings.append
    ids = [t.turn_id for t in s.turns]
    idset = set(ids)
    by_id = s.turns_by_id()

    if s.family not in FAMILIES:
        err(f"unknown family {s.family!r}")
    if len(ids) != len(idset):
        err("duplicate turn_ids")
    if [t.turn_index for t in s.turns] != list(range(len(s.turns))):
        err("turn_index must be 0..n-1 in file order")
    n = len(s.turns)
    if not (6 <= n <= 45):
        warn(f"turn count {n} outside the 6-45 range")

    # referential integrity
    for t in s.turns:
        for p in t.gold_parents:
            if p not in idset:
                err(f"{t.turn_id}.gold_parents references missing turn {p!r}")
            elif by_id[p].turn_index >= t.turn_index:
                err(f"{t.turn_id}.gold_parents references {p} with equal/later turn_index (forward/self edge)")
        if len(set(t.gold_parents)) != len(t.gold_parents):
            err(f"{t.turn_id}.gold_parents has duplicates")
        if t.superseded_by is not None:
            if t.superseded_by not in idset:
                err(f"{t.turn_id}.superseded_by references missing turn {t.superseded_by!r}")
            elif by_id[t.superseded_by].turn_index <= t.turn_index:
                err(f"{t.turn_id}.superseded_by must point to a later turn")
            if not t.stale:
                err(f"{t.turn_id} has superseded_by but stale=false")
        if t.stale and t.superseded_by is None:
            err(f"{t.turn_id} is stale but has no superseded_by")
        if not t.user_message.strip():
            err(f"{t.turn_id}.user_message is empty")
        hits = find_signposting(t.user_message)
        if hits:
            err(f"{t.turn_id}.user_message contains topic-switch signposting: {hits}")
    for field in ("evidence_turn_ids", "distractor_turn_ids"):
        for tid in getattr(s, field):
            if tid not in idset:
                err(f"{field} references missing turn {tid!r}")
    for tid in (s.evidence_spans or {}):
        if tid not in s.evidence_turn_ids:
            err(f"evidence_spans key {tid!r} is not in evidence_turn_ids")

    # query turn
    q = s.query
    if q.assistant_message is not None:
        err("last turn (the query) must have assistant_message = null")
    for t in s.history:
        if not (t.assistant_message or "").strip():
            err(f"{t.turn_id}.assistant_message is empty (only the query may be null)")
    if q.turn_id in s.evidence_turn_ids or q.turn_id in s.distractor_turn_ids:
        err("query turn must not appear in evidence or distractor sets")

    # evidence / distractor consistency
    ev, di = set(s.evidence_turn_ids), set(s.distractor_turn_ids)
    if ev & di:
        err(f"evidence and distractor sets overlap: {sorted(ev & di)}")
    hist_ids = {t.turn_id for t in s.history}
    uncovered = hist_ids - ev - di
    if uncovered:
        warn(f"history turns in neither evidence nor distractor sets: {sorted(uncovered)}")

    if not r.errors:
        closure = ancestors(q.turn_id, by_id)
        r.closure_matches_evidence = closure == ev
        if not r.closure_matches_evidence:
            msg = f"evidence {sorted(ev)} != ancestor closure {sorted(closure)}"
            if s.evidence_note:
                warn("REVIEWED closure mismatch: " + msg + f" (note: {s.evidence_note})")
            else:
                warn("FLAGGED closure mismatch, needs manual review: " + msg)
        # staleness: superseder should be in the closure whenever the stale turn is (§5.2)
        for t in s.turns:
            if t.stale and t.turn_id in closure and t.superseded_by not in closure:
                err(f"stale turn {t.turn_id} is in the closure but its superseder {t.superseded_by} is not")

    # checklist
    if not (2 <= len(s.answer_checklist) <= 4):
        warn(f"checklist has {len(s.answer_checklist)} items; expected 2-4")
    if len({c.id for c in s.answer_checklist}) != len(s.answer_checklist):
        err("duplicate checklist ids")
    if not any(c.required for c in s.answer_checklist):
        err("no required checklist items")
    neg_words = ("must not", "should not", "must NOT", "not describe", "not use", "not treat", "not assume", "not incorporate", "not mention")
    has_negative = any(any(w in c.criterion for w in neg_words) for c in s.answer_checklist)
    if s.family in NEGATIVE_CHECK_REQUIRED and not has_negative:
        err("no negative ('must not ...') checklist item")
    for c in s.answer_checklist:
        if len(c.criterion.split()) < 6:
            warn(f"checklist item {c.id} is very short; is it judgeable? ({c.criterion!r})")
    return r


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text())


def load_all(dir_path: str | Path) -> list[Scenario]:
    return [load_scenario(p) for p in sorted(Path(dir_path).glob("*.json"))]


def save_scenario(s: Scenario, dir_path: str | Path) -> Path:
    p = Path(dir_path) / f"{s.scenario_id}.json"
    p.write_text(json.dumps(s.model_dump(), indent=2, ensure_ascii=False) + "\n")
    return p


if __name__ == "__main__":
    import sys
    scenarios = load_all(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[1] / "data" / "scenarios")
    bad = 0
    for s in scenarios:
        r = validate_scenario(s)
        status = "OK " if r.ok else "ERR"
        bad += not r.ok
        print(f"{status} {s.scenario_id:36s} turns={len(s.turns):2d} ev={len(s.evidence_turn_ids):2d} di={len(s.distractor_turn_ids):2d}")
        for e in r.errors:
            print("     error:", e)
        for w in r.warnings:
            print("     warn: ", w)
    print(f"\n{len(scenarios)} scenarios, {bad} with errors")
    sys.exit(1 if bad else 0)
