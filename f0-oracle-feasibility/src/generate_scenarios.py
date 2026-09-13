"""Structure-first scenario generation (handoff §3.2).

For every scenario the gold dependency graph is decided *in code* (a family-specific
builder + seeded RNG) before any text exists. An LLM then writes dialogue that realizes
that exact outline. Only the user/assistant text and the answer checklist come from the
model; turn ids, parents, staleness, evidence and distractor sets are fixed by the plan.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import ROOT, append_jsonl, complete, extract_json, load_manifest  # noqa: E402
from schema import (ChecklistItem, Scenario, Turn, ancestors, save_scenario,  # noqa: E402
                    validate_scenario)

SCENARIO_DIR = ROOT / "data" / "scenarios"
GEN_LOG = ROOT / "results" / "raw" / "generation.jsonl"

LABELS = {
    "continuation": "CONTINUE", "topic_fork": "FORK", "resume": "RESUME", "new_root": "NEW_ROOT",
    "two_branch_join": "JOIN", "three_way_join": "JOIN", "semantic_decoy": "DECOY",
    "constraint_retention": "CONSTRAINT", "knowledge_update": "UPDATE",
    "ambiguous_reference": "AMBIGUOUS", "long_noisy_side_thread": "NOISE",
    "join_then_split": "SPLIT", "compound_turn": "COMPOUND",
}

# Varied domains so the benchmark is not all software engineering (handoff §3.2 step 1).
DOMAINS = [
    "designing a REST API for a payments product",
    "planning a cross-country house move with two kids and a dog",
    "organizing a 10-day trip to Japan for four friends",
    "a PhD student planning a field study on urban bird populations",
    "a small bakery deciding whether to open a second location",
    "renovating a 1920s kitchen on a fixed budget",
    "a nonprofit migrating its donor database to a new CRM",
    "training for a first marathon in 16 weeks",
    "launching a podcast about local history",
    "a board-game designer balancing a new card game",
    "a family choosing between two secondary schools",
    "a freelance photographer setting up a home studio",
    "a community garden applying for a municipal grant",
    "a startup negotiating a lease for its first office",
    "writing a fantasy novel and planning its magic system",
    "a hospital ward rolling out a new shift-scheduling process",
    "a vineyard choosing irrigation upgrades before harvest",
    "a high-school robotics team preparing for a regional competition",
    "a couple planning a 120-guest wedding on a lake",
    "a data team migrating nightly batch jobs to a new warehouse",
    "a restaurant redesigning its menu for a seasonal change",
    "a landlord deciding on energy-efficiency upgrades for a duplex",
    "a hobbyist building a backyard observatory",
    "a city library planning a summer reading program",
    "a film crew scheduling a low-budget short shoot",
    "a mobile app team fixing onboarding drop-off",
    "an amateur choir organizing a spring concert tour",
    "a farm cooperative setting up online ordering",
    "a museum planning a traveling exhibit on textiles",
    "a running club organizing a charity 10k",
    "a game studio planning a live-ops event calendar",
    "a dentist's office replacing its appointment software",
    "a sailing club replacing its aging dock",
    "a teacher designing a semester-long ecology project",
    "an indie hardware maker sourcing parts for a mechanical keyboard",
]


@dataclass
class TurnPlan:
    turn_id: str
    branch: str
    gold_parents: list[str]
    role: str            # evidence | distractor | query
    directive: str       # what this turn must accomplish
    stale: bool = False
    superseded_by: Optional[str] = None


@dataclass
class ScenarioPlan:
    family: str
    turns: list[TurnPlan]
    evidence_turn_ids: list[str]
    distractor_turn_ids: list[str]
    structure_summary: str
    checklist_guidance: str
    evidence_note: Optional[str] = None
    notes: str = ""

    def by_id(self) -> dict[str, TurnPlan]:
        return {t.turn_id: t for t in self.turns}


# ---------------------------------------------------------------------------
# Plan builders. Turn ids are assigned in chronological order after building.
# ---------------------------------------------------------------------------

def _chain(branch: str, n: int, first_parents: list[str], directives: list[str], role: str) -> list[TurnPlan]:
    """Helper: n turns in one branch, each depending on the previous. Ids are placeholders."""
    out = []
    for i in range(n):
        parents = first_parents if i == 0 else [f"{branch}{i}"]  # placeholder id of previous turn in branch
        out.append(TurnPlan(f"{branch}{i + 1}", branch, list(parents), role, directives[i]))
    return out


def _finalize(plan_turns: list[TurnPlan]) -> list[TurnPlan]:
    """Rename placeholder ids (A1, B2, ...) to t1..tn in the given chronological order."""
    mapping = {t.turn_id: f"t{i + 1}" for i, t in enumerate(plan_turns)}
    for t in plan_turns:
        t.turn_id = mapping[t.turn_id]
        t.gold_parents = [mapping[p] for p in t.gold_parents]
        if t.superseded_by:
            t.superseded_by = mapping[t.superseded_by]
    return plan_turns


def _interleave(rng: random.Random, *branches: list[TurnPlan]) -> list[TurnPlan]:
    """Merge branches into one chronological order, preserving order within each branch,
    and guaranteeing each branch's first turn precedes any later branch's turns only
    as needed for parents (parents are intra-branch here, so any interleaving is acyclic)."""
    queues = [list(b) for b in branches if b]
    out: list[TurnPlan] = []
    # always start with the first branch's first turn so the conversation opens on A
    out.append(queues[0].pop(0))
    while any(queues):
        weights = [len(q) for q in queues]
        i = rng.choices(range(len(queues)), weights=weights)[0]
        if queues[i]:
            out.append(queues[i].pop(0))
    return out


def _sets(turns: list[TurnPlan], evidence: set[str]) -> tuple[list[str], list[str]]:
    hist = [t.turn_id for t in turns[:-1]]
    ev = [t for t in hist if t in evidence]
    di = [t for t in hist if t not in evidence]
    return ev, di


def build_continuation(rng: random.Random) -> ScenarioPlan:
    n = rng.randint(5, 7)
    d = [f"Branch A turn {i + 1}: advance a single coherent thread on the premise; establish at least one concrete, specific fact (a number, a name, a date, or a rule) that later turns can build on." for i in range(n)]
    d[-1] = "Branch A, final history turn: build on the previous turn and settle a specific detail that the upcoming query will depend on."
    A = _chain("A", n, [], d, "evidence")
    q = TurnPlan("Q1", "Q", [f"A{n}"], "query", "QUERY: a natural follow-up that continues branch A and can only be answered correctly using specific facts from the A turns.")
    turns = _finalize(A + [q])
    ev = set(t.turn_id for t in turns[:-1])
    e, di = _sets(turns, ev)
    return ScenarioPlan("continuation", turns, e, di,
                        "A single linear thread A1→A2→...→query. Nothing structural differs here; every prior turn is relevant.",
                        "Checklist items should require specific facts established across the A turns.")


def build_topic_fork(rng: random.Random) -> ScenarioPlan:
    a_before = 2            # A1, A2 then fork
    a_after = rng.randint(1, 3)
    b_n = rng.randint(2, 3)
    dA = ["Branch A turn 1: open the main topic with concrete specifics.",
          "Branch A turn 2: add a specific detail or decision that a NEW subtopic (branch B) will later spin off from. This turn is the fork point."]
    dA += [f"Branch A turn {3 + i}: continue the main A thread in a direction that is NOT relevant to the branch-B subtopic (distractor for the query)." for i in range(a_after)]
    dB = [f"Branch B turn {i + 1}: {'spin off a narrower subtopic that stems directly from the fork-point detail in A2' if i == 0 else 'continue the B subtopic with concrete specifics'}." for i in range(b_n)]
    A = _chain("A", a_before + a_after, [], dA, "evidence")
    for t in A[a_before:]:
        t.role = "distractor"
    B = _chain("B", b_n, ["A2"], dB, "evidence")
    # chronological: A1 A2 then interleave the rest
    rest = _interleave(rng, B, A[a_before:])
    q = TurnPlan("Q1", "Q", [f"B{b_n}"], "query", "QUERY: continues branch B and needs facts from B plus the fork-point detail from A2; the later A turns are irrelevant.")
    turns = _finalize(A[:a_before] + rest + [q])
    by = {t.turn_id: t for t in turns}
    ev = ancestors(turns[-1].turn_id, {k: Turn(turn_id=k, turn_index=i, user_message="x", assistant_message="x", gold_parents=v.gold_parents) for i, (k, v) in enumerate(by.items())})
    e, di = _sets(turns, ev)
    return ScenarioPlan("topic_fork", turns, e, di,
                        "A1→A2, then subtopic B forks from A2 (B1's parent is A2). A also continues past the fork; those later A turns are distractors. Query continues B.",
                        "At least one item must require the fork-point detail from A2; the negative item must name something specific to the later A turns.")


def build_resume(rng: random.Random) -> ScenarioPlan:
    a_n = rng.randint(2, 3)
    b_n = rng.randint(3, 6)
    dA = [f"Branch A turn {i + 1}: {'open topic A with concrete specifics' if i == 0 else 'develop topic A; settle a specific detail the query will need'}." for i in range(a_n)]
    dB = [f"Branch B turn {i + 1}: {'switch to a genuinely different topic (same overall premise, different concern), without any meta-comment about switching' if i == 0 else 'continue topic B with its own concrete specifics'}." for i in range(b_n)]
    A = _chain("A", a_n, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    q = TurnPlan("Q1", "Q", [f"A{a_n}"], "query", "QUERY: returns to topic A after the B detour, picking up exactly where A left off, and needs specific A facts. It must not depend on anything in B.")
    turns = _finalize(A + B + [q])
    ev = set(t.turn_id for t in turns if t.branch == "A")
    e, di = _sets(turns, ev)
    return ScenarioPlan("resume", turns, e, di,
                        "A1→A2(→A3), then an unrelated branch B of several turns, then the query resumes A.",
                        "Negative item must name a specific B fact the answer must not import.")


def build_new_root(rng: random.Random) -> ScenarioPlan:
    a_n = rng.randint(5, 8)
    dA = [f"Branch A turn {i + 1}: develop topic A with concrete specifics." for i in range(a_n)]
    A = _chain("A", a_n, [], dA, "distractor")
    q = TurnPlan("Q1", "Q", [], "query", "QUERY: a brand-new, self-contained question with NO dependency on anything said before (different concern within the same broad premise, or a general question). It must be answerable from general knowledge plus what is in the query message itself.")
    turns = _finalize(A + [q])
    e, di = _sets(turns, set())
    return ScenarioPlan("new_root", turns, e, di,
                        "A1→...→An, then a query that starts a new root: its correct parent set is empty.",
                        "Items should check the new question is answered on its own terms; include one 'must not' item naming a specific A detail that would be a spurious import.")


def build_two_branch_join(rng: random.Random) -> ScenarioPlan:
    a_n, b_n, c_n = rng.randint(2, 4), rng.randint(2, 4), rng.randint(0, 3)
    dA = [f"Branch A turn {i + 1}: develop topic A; establish a specific fact/decision the query will need." for i in range(a_n)]
    dB = [f"Branch B turn {i + 1}: {'open a separate topic B (unrelated to A so far)' if i == 0 else 'develop topic B'}; establish a specific fact/decision the query will need." for i in range(b_n)]
    dC = [f"Branch C turn {i + 1}: an unrelated side concern; concrete but irrelevant to the query." for i in range(c_n)]
    A = _chain("A", a_n, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "evidence")
    C = _chain("C", c_n, [], dC, "distractor")
    body = _interleave(rng, A, B, C)
    q = TurnPlan("Q1", "Q", [f"A{a_n}", f"B{b_n}"], "query", "QUERY: genuinely requires BOTH branch A and branch B to answer (e.g., combines a decision from A with a constraint from B). A reader with only one branch should be unable to answer fully.")
    turns = _finalize(body + [q])
    ev = set(t.turn_id for t in turns if t.branch in ("A", "B"))
    e, di = _sets(turns, ev)
    return ScenarioPlan("two_branch_join", turns, e, di,
                        "Two separate branches A and B (each a chain from its own root), optionally a distractor branch C, then a query whose gold parents are the last A turn and the last B turn (a join).",
                        "One item must require a specific A fact and a different item a specific B fact, so a single-branch answer fails exactly one of them. The negative item names a C fact (or, if no C, a wrong inference).")


def build_three_way_join(rng: random.Random) -> ScenarioPlan:
    ns = [rng.randint(2, 3) for _ in range(3)]
    d_n = rng.randint(1, 3)
    brs = []
    for name, n in zip("ABC", ns):
        d = [f"Branch {name} turn {i + 1}: {'open a separate topic ' + name if i == 0 else 'develop topic ' + name}; establish a specific fact the query will need." for i in range(n)]
        brs.append(_chain(name, n, [], d, "evidence"))
    D = _chain("D", d_n, [], [f"Branch D turn {i + 1}: an unrelated side concern, concrete but irrelevant." for i in range(d_n)], "distractor")
    body = _interleave(rng, *brs, D)
    q = TurnPlan("Q1", "Q", [f"A{ns[0]}", f"B{ns[1]}", f"C{ns[2]}"], "query", "QUERY: genuinely requires all three branches A, B and C together (e.g., reconciling three separately-established facts).")
    turns = _finalize(body + [q])
    ev = set(t.turn_id for t in turns if t.branch in ("A", "B", "C"))
    e, di = _sets(turns, ev)
    return ScenarioPlan("three_way_join", turns, e, di,
                        "Three separate branches A, B, C plus a distractor branch D; the query joins A, B and C (three gold parents).",
                        "Three items, one per branch, each requiring a specific fact from that branch; plus one negative item naming a D fact.")


def build_semantic_decoy(rng: random.Random) -> ScenarioPlan:
    a_n, b_n = rng.randint(3, 4), rng.randint(3, 4)
    dA = [f"Branch A turn {i + 1}: discuss SYSTEM/ITEM X (the real subject); use specific values (versions, numbers, names) that differ from branch B." for i in range(a_n)]
    dB = [f"Branch B turn {i + 1}: discuss a DIFFERENT, unrelated system/item Y using the SAME kind of vocabulary and phrasing as branch A (deliberately lexically similar) but with different specific values." for i in range(b_n)]
    A = _chain("A", a_n, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    body = _interleave(rng, A, B)
    q = TurnPlan("Q1", "Q", [f"A{a_n}"], "query", "QUERY: continues branch A (about X) and is phrased with wording that overlaps heavily with branch B, so lexical similarity alone would point to B. It must be answerable only with A's specifics.")
    turns = _finalize(body + [q])
    ev = set(t.turn_id for t in turns if t.branch == "A")
    e, di = _sets(turns, ev)
    return ScenarioPlan("semantic_decoy", turns, e, di,
                        "Two lexically similar discussions about different things (A about X, B about Y); the query is about X but worded like B.",
                        "Negative item must name the specific B value that a confused answer would use instead of A's.")


def build_constraint_retention(rng: random.Random) -> ScenarioPlan:
    b_n = rng.randint(20, 27)
    dA = ["Branch A turn 1: the user states an EXACT, quotable rule or constraint (e.g., a hard limit, a prohibition, a fixed deadline) and the assistant acknowledges it precisely.",
          "Branch A turn 2: a short continuation of topic A that relies on the rule."]
    dB = [f"Branch B turn {i + 1}: on-topic-but-irrelevant filler within the same premise: a different concern, concrete and plausible, that never touches the A rule." for i in range(b_n)]
    A = _chain("A", 2, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    q = TurnPlan("Q1", "Q", ["A2"], "query", "QUERY: a request that can only be answered correctly by applying the exact rule from A1 (the naive answer without the rule would violate it). Do not restate the rule in the query.")
    turns = _finalize(A + B + [q])
    ev = {"t1", "t2"}
    e, di = _sets(turns, ev)
    return ScenarioPlan("constraint_retention", turns, e, di,
                        "A rule stated at the very start (A1), a brief A2, then 20+ turns of unrelated B filler, then a query that silently depends on the rule.",
                        "One item must require the answer to respect the exact rule; the negative item should name the naive violation and/or a specific B detail.")


def build_knowledge_update(rng: random.Random) -> ScenarioPlan:
    """Benchmark 1.1: the correction sits 12-20 turns before the query, and one later distractor
    casually restates the stale value, so staleness handling actually separates methods."""
    b_pre = rng.randint(2, 4)          # detour between A2 and the correction
    b_post = rng.randint(12, 20)       # distractors between the correction and the query
    restate_at = rng.randint(3, b_post - 2)
    dA = ["Branch A turn 1: the user states a specific fact (a price, version, date, quantity, or name) as VALUE_1 and the assistant works with it.",
          "Branch A turn 2: continue topic A building on VALUE_1 (e.g. the assistant derives a number from it).",
          "Branch A turn 3: the user CORRECTS the fact from A1 to VALUE_2 (clearly different), e.g. 'actually it's ... not ...'; the assistant acknowledges the correction and restates VALUE_2. No other new facts."]
    dB = [f"Branch B turn {i + 1}: an unrelated concern within the premise; concrete but irrelevant to topic A." for i in range(b_pre)]
    dC = []
    for i in range(b_post):
        if i == restate_at:
            dC.append(f"Branch C turn {i + 1}: an unrelated concern within the premise, in which the user or assistant casually mentions VALUE_1 (the OLD, superseded value from A1) in passing as if it were still current, e.g. 'like the {{VALUE_1}} we talked about'. This is a deliberate trap; it must not be corrected here and must not introduce any new A facts.")
        else:
            dC.append(f"Branch C turn {i + 1}: an unrelated concern within the premise (one coherent side thread, developed step by step); concrete but irrelevant to topic A.")
    A = _chain("A", 3, [], dA, "evidence")
    A[0].stale, A[0].superseded_by = True, "A3"
    B = _chain("B", b_pre, [], dB, "distractor")
    C = _chain("C", b_post, [], dC, "distractor")
    body = A[:2] + B + A[2:] + C
    q = TurnPlan("Q1", "Q", ["A3"], "query", "QUERY: a follow-up on topic A whose correct answer depends on using VALUE_2 (the corrected value); using VALUE_1 would give a wrong answer. Do not restate either value in the query.")
    turns = _finalize(body + [q])
    ev = set(t.turn_id for t in turns if t.branch == "A")
    e, di = _sets(turns, ev)
    return ScenarioPlan("knowledge_update", turns, e, di,
                        "A1 states a fact, A2 continues, a short B detour, then A3 corrects the fact (A1 is marked stale, superseded by A3); then 12-20 turns of an unrelated C thread, one of which casually repeats the OLD value; the query needs the corrected value.",
                        "One item requires VALUE_2 to be used; the negative item says the answer must not use VALUE_1 (name it). Do not require the answer to mention VALUE_1 or the correction explicitly; using VALUE_2 correctly is sufficient.")


def build_ambiguous_reference(rng: random.Random) -> ScenarioPlan:
    a_n, b_n = 2, rng.randint(2, 3)
    c_n = rng.randint(1, 2)   # >=1 so the scenario always has >= 6 turns
    dA = ["Branch A turn 1: introduce ENTITY_1 (a specific person, team, vendor, venue or object) with a distinctive name and specifics.",
          "Branch A turn 2: continue about ENTITY_1; settle a specific detail (a constraint, availability, requirement)."]
    dB = [f"Branch B turn {i + 1}: {'introduce a DIFFERENT entity ENTITY_2 of the same kind (so a pronoun could refer to either)' if i == 0 else 'continue about ENTITY_2'} with its own distinct specifics." for i in range(b_n)]
    dC = [f"Branch C turn {i + 1}: an unrelated concern; concrete but irrelevant." for i in range(c_n)]
    A = _chain("A", a_n, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    C = _chain("C", c_n, [], dC, "distractor")
    body = A + _interleave(rng, B, C) if C else A + B
    q = TurnPlan("Q1", "Q", ["A2"], "query", "QUERY: refers to ENTITY_1 only by a pronoun or deictic ('they', 'it', 'that one', 'the same place') and asks something that needs A2's specific detail; the wording alone would fit ENTITY_2 equally well.")
    turns = _finalize(body + [q])
    ev = set(t.turn_id for t in turns if t.branch == "A")
    e, di = _sets(turns, ev)
    return ScenarioPlan("ambiguous_reference", turns, e, di,
                        "Entity 1 is introduced in A, entity 2 in B; the query uses a pronoun that resolves to entity 1 only via branch structure.",
                        "One item requires resolving the reference to ENTITY_1 and using A2's detail; the negative item says it must not resolve to ENTITY_2 (name it).")


def build_long_noisy_side_thread(rng: random.Random) -> ScenarioPlan:
    b_n = rng.randint(30, 38)
    dA = ["Branch A turn 1: open topic A with concrete specifics.",
          "Branch A turn 2: settle a specific detail the query will need."]
    dB = [f"Branch B turn {i + 1}: a long unrelated side thread (one coherent different concern, developed step by step); concrete, plausible, never touching topic A." for i in range(b_n)]
    A = _chain("A", 2, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    q = TurnPlan("Q1", "Q", ["A2"], "query", "QUERY: returns to topic A after the long B thread and needs A's specifics; nothing from B is relevant.")
    turns = _finalize(A + B + [q])
    e, di = _sets(turns, {"t1", "t2"})
    return ScenarioPlan("long_noisy_side_thread", turns, e, di,
                        "Two A turns, then 30+ turns of an unrelated B thread, then the query resumes A.",
                        "Negative item names a specific B fact the answer must not import.")


def build_join_then_split(rng: random.Random) -> ScenarioPlan:
    a_n, b_n, j_n = 2, 2, rng.randint(1, 2)
    dA = ["Branch A turn 1: open topic A with concrete specifics.", "Branch A turn 2: settle a specific A detail."]
    dB = ["Branch B turn 1: open a separate topic B with concrete specifics.", "Branch B turn 2: settle a specific B detail."]
    dJ = [f"Join turn {i + 1}: {'the user brings A and B together (a decision that combines both)' if i == 0 else 'continue the combined A+B discussion'}; introduce combined-specific facts that are NOT needed for the final query." for i in range(j_n)]
    A = _chain("A", a_n, [], dA, "evidence")
    B = _chain("B", b_n, [], dB, "distractor")
    J = _chain("J", j_n, ["A2", "B2"], dJ, "distractor")
    q = TurnPlan("Q1", "Q", ["A2"], "query", "QUERY: returns to topic A ALONE (a pure A follow-up that needs only A's specifics), ignoring both B and the joined discussion.")
    turns = _finalize(A + B + J + [q])
    e, di = _sets(turns, {"t1", "t2"})
    return ScenarioPlan("join_then_split", turns, e, di,
                        "A and B are discussed, then joined (J's parents are A2 and B2), then the query splits back to A only (parent A2).",
                        "One item needs an A detail; the negative item names a B or J-specific fact that must not be imported.")


def build_compound_turn(rng: random.Random, variant: str = "second_request") -> ScenarioPlan:
    """A compound turn bundles an A continuation (first request) with a new B request (second).
    variant "second_request": the query follows up on B only (evidence = the compound turn alone).
    variant "first_request" (benchmark 1.1): the query follows up on A; the B request spawns its
    own distractor branch, so the compound turn's B half is the unavoidable irrelevant content."""
    dA = ["Branch A turn 1: open topic A with concrete specifics.", "Branch A turn 2: develop topic A; settle a specific detail."]
    dC = ["COMPOUND turn: the user's single message bundles TWO unrelated requests: (1) a continuation of topic A that needs a specific new A fact settled, and (2) a brand-new, self-contained request on topic B (a different concern) with its own specifics. The assistant answers both parts in one reply, giving concrete A-specific and B-specific facts."]
    A = _chain("A", 2, [], dA, "evidence" if variant == "first_request" else "distractor")
    C = TurnPlan("C1", "C", ["A2"], "evidence", dC[0])
    if variant == "second_request":
        a_after = rng.randint(2, 4)
        after = _chain("D", a_after, ["C1"], [f"Branch A turn {3 + i}: continue ONLY topic A (never mention B)." for i in range(a_after)], "distractor")
        for tt in after:
            tt.branch = "A"
        q = TurnPlan("Q1", "Q", ["C1"], "query", "QUERY: a follow-up ONLY on the B part of the compound turn (needs the B-specific facts the assistant gave there); nothing about topic A is relevant.")
        turns = _finalize(A + [C] + after + [q])
        e, di = _sets(turns, {"t3"})
        return ScenarioPlan("compound_turn", turns, e, di,
                            "A1->A2->C (a compound turn bundling an A continuation with an unrelated B request)->A3..; the query follows up on B only, so its parent is C.",
                            "One item requires B-specific facts from the compound turn; the negative item names an A detail that must not be imported.",
                            evidence_note="Query depends only on the B half of the compound turn t3. Its ancestor closure {t3,t2,t1} includes A turns that are conversationally upstream of t3 but not needed for the B question; evidence is deliberately just {t3}. This is the granularity cost the family is designed to expose.")
    b_after = rng.randint(2, 4)
    after = _chain("B", b_after, ["C1"], [f"Branch B turn {i + 1}: continue ONLY topic B (the second request from the compound turn); never mention topic A." for i in range(b_after)], "distractor")
    q = TurnPlan("Q1", "Q", ["C1"], "query", "QUERY: a follow-up ONLY on the A part of the compound turn (needs the A facts from A1, A2 and the A half of the compound reply); nothing about topic B is relevant.")
    turns = _finalize(A + [C] + after + [q])
    e, di = _sets(turns, {"t1", "t2", "t3"})
    return ScenarioPlan("compound_turn", turns, e, di,
                        "A1->A2->C (a compound turn bundling an A continuation with an unrelated B request)->B1..; the query follows up on A only, so its parent is C and its evidence is the A chain.",
                        "Items require A facts (at least one from the A half of the compound reply); the negative item names a B detail (from the compound turn's B half or the B branch) that must not be imported.",
                        evidence_note="Query depends on the A half of the compound turn t3 plus t1, t2; evidence equals the closure, but t3's B half is unavoidable irrelevant content at turn granularity (see evidence_spans).")


BUILDERS = {
    "continuation": build_continuation, "topic_fork": build_topic_fork, "resume": build_resume,
    "new_root": build_new_root, "two_branch_join": build_two_branch_join,
    "three_way_join": build_three_way_join, "semantic_decoy": build_semantic_decoy,
    "constraint_retention": build_constraint_retention, "knowledge_update": build_knowledge_update,
    "ambiguous_reference": build_ambiguous_reference, "long_noisy_side_thread": build_long_noisy_side_thread,
    "join_then_split": build_join_then_split, "compound_turn": build_compound_turn,
}

# ---------------------------------------------------------------------------
# Generation prompt (fixed template, handoff §3.2)
# ---------------------------------------------------------------------------

GENERATION_PROMPT = """You are writing a realistic multi-turn conversation between a user and an AI assistant for a research benchmark on conversational context. The conversation's dependency structure has ALREADY been decided and is given below as a turn-by-turn outline. Your job is to write natural dialogue that realizes exactly that structure.

PREMISE: {premise}

STRUCTURE ({family}): {structure_summary}

OUTLINE (write these turns, in this order, with these ids):
{outline}

RULES
1. Write every turn listed, in order, with the exact turn_id given. Do not add, drop, merge or reorder turns.
2. Each user message is 1-4 sentences; each assistant message is 2-6 sentences. Plain prose, no markdown headers or bullet lists.
3. Make evidence turns carry concrete, specific, checkable facts: exact numbers, names, dates, versions, rules. Vague content makes the benchmark useless.
4. Distractor turns must be plausible and on-premise but genuinely irrelevant to the query. Do not let distractor turns restate, hint at, or resolve anything the query needs.
5. The conversation must read as one continuous chat, and topic changes happen WITHOUT announcement. BANNED in user messages (the output is rejected if any appear): "on a different note", "on a separate note", "separately", "unrelated", "switching topics", "changing the subject", "going back to", "coming back to", "back to the ...", "circling back", "one more thing", "while we're at it", "side note", "meanwhile", "different question", "new topic", and any similar signposting. To change topic, the user simply asks the next question directly ("What size tent do we need?"). To return to an earlier topic, the user simply asks a question that is only meaningful for that topic ("What was the point threshold for the armor set?"); the content, not a transition phrase, signals what the message is about.
6. The final turn is the QUERY. Write only its user_message; set its assistant_message to null. The query must be natural and must not restate the facts it depends on.
7. Then write an answer_checklist of 2-4 items that a third party could judge TRUE/FALSE by reading only the evidence turns plus a candidate answer. Each criterion must name the specific fact/value it checks. {checklist_guidance} Every checklist must include at least one negative item phrased "The answer must not ...".
8. Also write reference_answer: a 2-5 sentence ideal answer to the query using only the evidence turns.

Return ONLY a JSON object of this shape, no prose before or after:
{{
  "turns": [{{"turn_id": "t1", "user_message": "...", "assistant_message": "..."}}, ..., {{"turn_id": "tN", "user_message": "...", "assistant_message": null}}],
  "answer_checklist": [{{"id": "c1", "criterion": "...", "required": true}}, ...],
  "reference_answer": "...",
  "notes": "one or two sentences on which turns hold the facts the query needs and which are the traps"
}}"""


def render_outline(plan: ScenarioPlan) -> str:
    lines = []
    for t in plan.turns:
        role = {"evidence": "EVIDENCE", "distractor": "DISTRACTOR", "query": "QUERY"}[t.role]
        parents = ", ".join(t.gold_parents) if t.gold_parents else "none (new root)"
        extra = f" [this turn is later corrected by {t.superseded_by}]" if t.stale else ""
        lines.append(f"- {t.turn_id} (branch {t.branch}, {role}, depends on: {parents}){extra}: {t.directive}")
    return "\n".join(lines)


def realize(plan: ScenarioPlan, scenario_id: str, premise: str, manifest: dict, rng: random.Random,
            max_attempts: int = 3) -> tuple[Scenario, dict]:
    gen = manifest["models"]["generator"]
    prompt = GENERATION_PROMPT.format(premise=premise, family=plan.family, structure_summary=plan.structure_summary,
                                      outline=render_outline(plan), checklist_guidance=plan.checklist_guidance)
    temperature = round(rng.uniform(0.7, 0.9), 2)
    last_problem = ""
    for attempt in range(1, max_attempts + 1):
        p = prompt if not last_problem else prompt + f"\n\nYour previous attempt was rejected because: {last_problem}. Fix that."
        res = complete(gen["id"], p, temperature=temperature, max_tokens=gen["max_tokens"], purpose="generation", ref=scenario_id)
        log = {"scenario_id": scenario_id, "attempt": attempt, "temperature": temperature, **res.to_dict()}
        try:
            data = extract_json(res.text)
            scenario = assemble(plan, scenario_id, premise, data)
        except Exception as e:  # noqa: BLE001
            last_problem = f"output could not be parsed/assembled ({e})"
            log["problem"] = last_problem
            append_jsonl(GEN_LOG, log)
            continue
        v = validate_scenario(scenario)
        log["validation_errors"], log["validation_warnings"] = v.errors, v.warnings
        append_jsonl(GEN_LOG, log)
        if v.ok:
            return scenario, log
        last_problem = "; ".join(v.errors)
    raise RuntimeError(f"{scenario_id}: failed after {max_attempts} attempts: {last_problem}")


def assemble(plan: ScenarioPlan, scenario_id: str, premise: str, data: dict) -> Scenario:
    got = {t["turn_id"]: t for t in data["turns"]}
    expected = [t.turn_id for t in plan.turns]
    if list(got) != expected:
        raise ValueError(f"turn ids {list(got)} != expected {expected}")
    turns = []
    for i, tp in enumerate(plan.turns):
        g = got[tp.turn_id]
        turns.append(Turn(
            turn_id=tp.turn_id, turn_index=i,
            user_message=(g.get("user_message") or "").strip(),
            assistant_message=None if tp.role == "query" else (g.get("assistant_message") or "").strip(),
            gold_parents=list(tp.gold_parents), stale=tp.stale, superseded_by=tp.superseded_by,
        ))
    checklist = [ChecklistItem(id=c["id"], criterion=c["criterion"].strip(), required=bool(c.get("required", True)))
                 for c in data.get("answer_checklist", [])]
    notes = (data.get("notes") or "").strip()
    ref = (data.get("reference_answer") or "").strip()
    if ref:
        notes = (notes + "\n\nReference answer: " + ref).strip()
    spans = None
    if plan.family == "compound_turn":
        spans = {"t3": "first_request" if "A half" in (plan.evidence_note or "") else "second_request"}
    return Scenario(
        scenario_id=scenario_id, family=plan.family, label=LABELS[plan.family], turns=turns,
        evidence_turn_ids=list(plan.evidence_turn_ids), distractor_turn_ids=list(plan.distractor_turn_ids),
        answer_checklist=checklist, notes=notes, evidence_note=plan.evidence_note, premise=premise,
        evidence_spans=spans, benchmark_version="1.1",
    )


def generate(family: str, index: int, seed: int, manifest: dict, domains_used: set[str]) -> Scenario:
    scenario_id = f"{family}_{index:03d}"
    rng = random.Random(f"{seed}:{scenario_id}")
    if family == "compound_turn" and index >= 11:
        plan = build_compound_turn(rng, variant="first_request")
    else:
        plan = BUILDERS[family](rng)
    # spread domains: prefer one not yet used in this batch
    pool = [d for d in DOMAINS if d not in domains_used] or DOMAINS
    premise = rng.choice(pool)
    domains_used.add(premise)
    scenario, log = realize(plan, scenario_id, premise, manifest, rng)
    path = save_scenario(scenario, SCENARIO_DIR)
    v = validate_scenario(scenario)
    flag = " (closure mismatch: " + ("reviewed" if scenario.evidence_note else "FLAGGED") + ")" if not v.closure_matches_evidence else ""
    print(f"  wrote {path.name}: {len(scenario.turns)} turns, {len(scenario.answer_checklist)} checks, "
          f"{log['input_tokens']}+{log['output_tokens']} tok, {log['latency_s']:.0f}s, attempt {log['attempt']}{flag}")
    for w in v.warnings:
        print("    warn:", w)
    return scenario


PILOT = [("two_branch_join", 3), ("knowledge_update", 3), ("resume", 2), ("compound_turn", 2)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="generate the 10 pilot scenarios")
    ap.add_argument("--family", choices=list(BUILDERS))
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--start", type=int, default=1, help="first index for --family")
    ap.add_argument("--all", action="store_true", help="fill every family to its manifest target, skipping existing files")
    ap.add_argument("--dry-run", action="store_true", help="print outlines only, no LLM calls")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    manifest = load_manifest()
    seed = manifest["run"]["seed"]
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, int]] = []
    if args.pilot:
        for fam, n in PILOT:
            jobs += [(fam, i) for i in range(1, n + 1)]
    elif args.all:
        for fam, target in manifest["benchmark"]["family_targets"].items():
            jobs += [(fam, i) for i in range(1, target + 1)]
    elif args.family:
        jobs += [(args.family, i) for i in range(args.start, args.start + args.count)]
    else:
        ap.error("choose --pilot, --all, or --family")

    domains_used: set[str] = set()
    for s in SCENARIO_DIR.glob("*.json"):
        try:
            domains_used.add(json.loads(s.read_text()).get("premise") or "")
        except Exception:  # noqa: BLE001
            pass

    t0 = time.time()
    pending = []
    for fam, i in jobs:
        sid = f"{fam}_{i:03d}"
        if (SCENARIO_DIR / f"{sid}.json").exists():
            continue
        if args.dry_run:
            plan = BUILDERS[fam](random.Random(f"{seed}:{sid}"))
            print(f"\n== {sid} ==\n{plan.structure_summary}\n{render_outline(plan)}\nevidence={plan.evidence_turn_ids} distractors={plan.distractor_turn_ids}")
            continue
        pending.append((fam, i))
    if args.dry_run:
        return
    print(f"{len(pending)} scenarios to generate ({len(jobs) - len(pending)} already exist)", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from cost import BudgetExceeded, ledger
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(generate, fam, i, seed, manifest, domains_used): f"{fam}_{i:03d}" for fam, i in pending}
        for n, f in enumerate(as_completed(futs), 1):
            sid = futs[f]
            try:
                f.result()
            except BudgetExceeded as e:
                print("STOP:", e, flush=True); ex.shutdown(cancel_futures=True); break
            except Exception as e:  # noqa: BLE001
                failed.append(sid); print(f"  FAILED {sid}: {e}", flush=True)
            if n % 10 == 0:
                print(f"  [{n}/{len(pending)}] spend ${ledger().total:.2f}", flush=True)
    print(f"done in {time.time() - t0:.0f}s, {len(failed)} failed: {failed}\n{ledger().report()}")


if __name__ == "__main__":
    main()
