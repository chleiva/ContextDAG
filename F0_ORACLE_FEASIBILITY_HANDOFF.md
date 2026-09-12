# ContextDAG — F0 Oracle Feasibility: Execution Handoff

Version 1.0 | 12 September 2026
Derived from ContextDAG R&D Specification v0.4, §12.1 (F0) and supporting sections. This document is self-contained: a fresh Claude Code session should be able to execute it from an empty repository without access to any other ContextDAG document. If you also have the full R&D Specification (v0.4) available, share it too for background — but nothing here depends on it.

## How to use this document

Paste this entire file as the first message to a new Claude Code session in a new, empty repository. Tell it to read the whole thing before writing any code, then follow "Section 10: Step-by-step execution plan" in order, checking in with you at the checkpoints marked **STOP AND CHECK IN**. Do not let it run the full-scale experiment unattended on the first pass — the checkpoints exist to catch schema mistakes and cost surprises before they multiply across ~140 scenarios × 6 context methods × 2 models × 2 window budgets (roughly 2,000+ LLM calls before judging, more with the LLM-judge pass).

---

## 0. Repository setup (do this before any code)

The repo is public from the start (`ContextDAG`), so get the housekeeping right in the first commit rather than retrofitting it later.

**Naming heads-up.** This project was originally going to be called "ContextGraph," but that name turned out to be already in active commercial use — a live SaaS product at contextgraph.art (public beta, pricing, 10,000+ repos analyzed), a pre-launch startup at contextgraph.tech, an existing `github.com/contextgraph` organization, and several unrelated GitHub repos self-titled "Context-Graph." **ContextDAG** was chosen specifically to avoid that collision and to be more technically precise (the structure really is a DAG, not just "a graph"). A search pass at the time of writing found no direct collisions for "ContextDAG" on GitHub or PyPI — but re-check yourself immediately before creating the repo, since availability can change and no search is exhaustive: check `github.com/ContextDAG` and `github.com/<your-username>/ContextDAG`, PyPI, and npm one more time first.

**License.** Apache-2.0 for all code. Do not use MIT for this project: Apache-2.0's explicit patent grant matters more than usual for LLM tooling and signals the project is meant to be depended on, not just sampled. Add the standard `LICENSE` file (Apache-2.0 text) and a `NOTICE` file at the repo root in the first commit.

License structure — three distinct things, three distinct treatments, and this should be spelled out in the README, not left implicit:
- **Code**: Apache-2.0 (`LICENSE`).
- **Any benchmark data this project creates itself** (the synthetic scenarios built in §3, and eventually the full ContextDAG-Bench): CC-BY-4.0 — the standard choice for a research benchmark meant to be reused and cited. Note this separately in the README and in a `benchmarks/LICENSE` or header comment, since it's a different license from the code.
- **External benchmark data** (NTM, TopiOCQA, LoCoMo, LongMemEval, or anything sourced per §3.4): never redistribute it in this repo. Ship download/adapter scripts instead, and record each source's own license and terms in a `DATA_SOURCES.md` file.

**Repo description** (GitHub's short description field, and the README's opening line). Avoid language implying graph-structured or multi-parent conversation context is novel in itself — a prior-art review already found close precedents (automatic multi-parent DAGs exist for agent trajectories; manual multi-parent and tree-structured conversation UIs exist for human chat), so an overclaiming description will read as uninformed to exactly the audience likely to check. Use one of:

> Research framework for dependency-graph context management in multi-turn LLM conversations — routes context by what a message actually depends on, not chronology, with an oracle-first benchmark testing whether that helps versus full-history, retrieval, and compression baselines.

or, shorter:

> Does dependency-structured conversation context beat full history, retrieval, and compression? An open research framework and benchmark to find out.

Suggested topics/tags: `llm`, `nlp`, `conversational-ai`, `context-management`, `benchmark`, `research`.

**README status note.** Since the repo starts with only F0 code, say so explicitly near the top of the README — e.g. "Early-stage research: this repository currently contains the F0 oracle feasibility study, the first step in a staged evaluation plan before any automatic system is built." Anyone starring or cloning early should not mistake this for a finished framework.

---

## 1. What F0 is and why it exists

ContextDAG's core hypothesis is that representing a conversation as a dependency graph (not a flat transcript) lets you build model context from only the branches a new message actually depends on — including, when needed, two or more previously separate branches at once (a "join") — while using substantially fewer tokens than sending the whole history, without losing answer quality.

Before building any automatic routing, UI, or infrastructure, F0 asks a narrower, cheaper question first: **if you had a perfect (oracle/gold-labeled) dependency graph, handed to you rather than inferred, does the resulting context actually beat strong existing baselines on the quality-vs-tokens trade-off?** If the answer is no, there is no point building an automatic router to approximate something that doesn't help even in the best case. This is a deliberate "test the ceiling before building the machine" step.

F0 pre-registered hypothesis (H1, adapted for this run): an oracle graph-based context will reduce average context tokens by a material margin (default threshold: **≥40%** vs. full history — see §9 for how to treat this as adjustable) relative to full history, while remaining **non-inferior** on task quality (default margin: quality score within **5 percentage points** of full history, or better). Both thresholds are placeholders consistent with the parent project's spirit, not fixed facts — confirm or adjust them with whoever owns this project *before* looking at results, and record whatever you decide in `manifest.yaml` (§8) before the full run. Changing them after seeing results defeats the point.

F0 is entirely offline: no automatic router, no candidate generation, no UI. Every context set is either a fixed baseline (full history, sliding window, rolling summary, semantic retrieval) or derived directly from hand-authored gold dependency annotations (oracle tree, oracle DAG). The only thing under test is: *given the right structure, does it help?*

---

## 2. Core data model

A **turn** is one user message + the assistant's reply to it. A **scenario** is one synthetic (or sourced) multi-turn conversation, ending in a "query turn" whose correct context (which earlier turns it depends on) has been hand-annotated as ground truth.

### 2.1 Turn schema

```json
{
  "turn_id": "t1",
  "turn_index": 0,
  "user_message": "We are designing an API. It must remain backwards compatible.",
  "assistant_message": "Understood — I'll flag any breaking change explicitly.",
  "gold_parents": [],
  "stale": false,
  "superseded_by": null
}
```

- `gold_parents`: list of `turn_id`s this turn *directly* depends on to be correctly interpreted. Empty list = new root (no dependency on prior conversation). One entry = normal continuation or resume. Two or more entries = a join (this turn genuinely requires two previously separate branches to be interpreted or answered correctly).
- `stale` / `superseded_by`: set when a later turn revises or overrides a fact established in this turn (e.g., a price or version number gets corrected downstream). `superseded_by` points at the turn that overrides it.
- Every turn in a scenario needs `gold_parents` set, not just the final one — the annotation is of the whole conversation's dependency structure, because oracle-tree and oracle-DAG context construction both need to walk parent chains, which requires every turn's parents to be known, not only the last turn's.

### 2.2 Scenario schema

```json
{
  "scenario_id": "join_two_branch_014",
  "family": "two_branch_join",
  "label": "JOIN",
  "turns": [ /* array of Turn objects, see 2.1, chronological order, last turn = the query */ ],
  "evidence_turn_ids": ["t3", "t7", "t8"],
  "distractor_turn_ids": ["t4", "t5", "t6"],
  "answer_checklist": [
    {"id": "c1", "criterion": "Answer must specify that refresh tokens rotate on every use.", "required": true},
    {"id": "c2", "criterion": "Answer must reference the AWS API Gateway / Lambda serverless architecture from the second branch.", "required": true},
    {"id": "c3", "criterion": "Answer must not describe rotating access tokens (a distinct, unrelated fact from a distractor turn) as if it were the rotation policy in question.", "required": true}
  ],
  "notes": "Query turn (last in `turns`) depends on both the auth branch (t3) and the infra branch (t7/t8); a single-parent tree can only pick one and should fail c1 or c2, not both."
}
```

- **The last turn in `turns` is always the query under test.** Its `assistant_message` should be `null` in the scenario file — that's what the pipeline generates and scores, per context method and per model. All earlier turns keep their real (pre-written) `assistant_message`, since they're just conversation history the model reads.
- `evidence_turn_ids`: the turns whose *content* is actually required to answer the query correctly. In most cases this equals the ancestor closure of the query turn's `gold_parents` (following `gold_parents` recursively), but occasionally a parent is conversationally necessary without itself holding the needed fact (the fact is in *its* ancestor). Compute the ancestor closure programmatically, then hand-check it matches `evidence_turn_ids` for each scenario during generation — don't just assume they're identical without checking, especially for `resume`, `knowledge_update`, and `join_then_split` scenarios.
- `distractor_turn_ids`: turns that exist in the conversation but are *not* in the evidence set — the point of including them is to see which context methods pull them in anyway (full history always will; a good retrieval or oracle method shouldn't).
- `answer_checklist`: the actual scoring instrument (see §7.3). Write 2–4 checklist items per scenario. At least one item per scenario should be a **negative check** ("must not..."), since a method that gets the right facts by accident but also drags in wrong ones should not score as fully correct.

---

## 3. Synthetic benchmark: what to generate, and why

You need **enough labeled scenarios to detect a real effect, covering every structural pattern the hypothesis depends on** — not a large dataset, a *precise* one. Real conversations rarely isolate one structural pattern at a time, which is exactly why F0 uses constructed scenarios: each one is built to cleanly test one specific failure mode a flat-history or naive-retrieval approach would have, with a checkable right answer.

### 3.1 Scenario families and target counts

Build **at least 130 scenarios total**, distributed across these families (these come from the parent project's benchmark design and are not arbitrary — each isolates a distinct claim in the hypothesis):

| Family | Target count | What it tests | Pattern |
|---|---|---|---|
| `continuation` | 10 | Baseline sanity case — nothing structural should differ across methods here. | A1 → A2 → A3, query continues A. |
| `topic_fork` | 10 | New subtopic branching off an earlier shared point. | A1 → A2; B1 forks from A2. |
| `resume` | 15 | Returning to an inactive branch after distractor turns. | A1,A2 → B1,B2 (distractor) → A3 (query). |
| `new_root` | 8 | Truly unrelated new topic — correct answer is an *empty* parent set. | A… then unrelated C1 (query). |
| `two_branch_join` | 15 | Query genuinely requires two previously separate branches. | A-branch + B-branch → J1 (query, 2 gold parents). |
| `three_way_join` | 8 | Stress sparse 3-parent selection. | A+B+C → J (query, 3 gold parents). |
| `semantic_decoy` | 12 | Similar wording, wrong branch — tests whether a method confuses lexical similarity with real dependency. | Two "deployment" discussions for different, unrelated systems. |
| `constraint_retention` | 12 | An exact rule stated early must survive a long distractor thread. | "Do not change the public API" (T1) … 20+ distractor turns … query relies on that constraint. |
| `knowledge_update` | 12 | A fact from one branch is later corrected; tests staleness handling. | Price/version/date stated, then corrected later in the same branch; query must use the corrected value. |
| `ambiguous_reference` | 8 | Pronoun/deictic reference needs branch resolution. | "They can do Tuesday" after multiple candidate entities were introduced across branches. |
| `long_noisy_side_thread` | 10 | Many irrelevant turns between the evidence and the query. | A (evidence) → 30–40 turns of unrelated B → A query. |
| `join_then_split` | 10 | A joined discussion later returns to using only one of its source branches. | A+B → J → resume A only. |
| `compound_turn` | 10 | A single turn bundles two unrelated requests in one message — stresses whether turn-level granularity forces a spurious join or an over-broad single selection. | "Rename the field, and separately, what's EC2 pricing in London?" |

That's 140 at the counts above; treat 130 as the floor and 140+ as the target if time/cost allows. Keep each scenario between 6 and 45 turns (short families like `continuation`/`new_root` can be short; `long_noisy_side_thread` and `constraint_retention` need enough distractor bulk to be a real test — pad those with plausible, on-topic-but-irrelevant filler turns, not lorem-ipsum).

### 3.2 How to actually generate them

Do **not** hand-write 140 natural-sounding conversations yourself turn by turn — use an LLM to draft them against a strict template, then validate mechanically and by spot-reading. Process per scenario:

1. Pick the family and fill in a concrete premise (a domain: API design, a house move, trip planning, a research project, a small business decision — vary domains across scenarios so the benchmark isn't all "software engineering," which would narrow what any result generalizes to).
2. Write the **gold dependency graph first**, as a plain list of `(turn_id, gold_parents)` pairs, before generating any text. This is the critical discipline: the structure is ground truth and must be decided independently of how naturally the text reads, not reverse-engineered from generated text afterward.
3. Prompt an LLM to write natural dialogue turns that *realize* that exact graph — give it the turn-by-turn outline (who says what topic, which turns are distractors, which turn is the query) and ask it to write plausible `user_message`/`assistant_message` pairs, explicitly instructing it not to add meta-commentary like "switching topics now."
4. Write the `answer_checklist` yourself (or have the LLM draft it, then you tighten it) directly from the gold graph and the premise — the checklist should be answerable by reading only the `evidence_turn_ids`, not the full conversation, as a manual sanity check.
5. Validate programmatically (§3.3) before considering the scenario finished.

Use a fixed generation prompt template (put it in `src/generate_scenarios.py` as a constant) so all scenarios have consistent style; vary temperature slightly (0.7–0.9) for natural-sounding variety across scenarios, but keep the *structural* outline deterministic (temperature 0 equivalent) since that's the part that must be exactly what you intended.

### 3.3 Validation checklist (run this on every scenario before it enters the benchmark)

- [ ] Every `turn_id` referenced in any `gold_parents`, `evidence_turn_ids`, `distractor_turn_ids`, or `superseded_by` field actually exists in `turns`.
- [ ] No `gold_parents` entry points to a turn with an equal or later `turn_index` (no forward or self edges — the graph must be acyclic by construction).
- [ ] The last turn's `assistant_message` is `null`.
- [ ] `evidence_turn_ids` is a subset of `turns` and, for the large majority of scenarios, matches the ancestor closure of the query turn's `gold_parents` computed via the algorithm in §5.5 — flag and manually review any scenario where it doesn't.
- [ ] `distractor_turn_ids` and `evidence_turn_ids` are disjoint.
- [ ] Every `answer_checklist` item is phrased so a third party could judge it true/false by reading only the evidence turns plus the model's answer — reject vague criteria like "answer should be good."
- [ ] At least one negative ("must not...") checklist item exists per scenario where a plausible wrong-branch answer exists (all families except `continuation`/`new_root` should have one).
- [ ] Read every 10th scenario in full yourself before running anything at scale — LLM-generated structured data drifts in ways schema validation won't catch (e.g., a "distractor" that's actually mildly relevant).

### 3.4 Optional: sourcing NTM (Context-Agent's benchmark)

The Context-Agent paper (ACL Findings 2026) introduces a benchmark called NTM that the parent ContextDAG specification recommends including alongside the custom benchmark. As of this writing, the paper states code will be released upon acceptance but does not give a confirmed public repository URL, and no verified repository could be located during the prior-art review this document is based on. **Treat NTM inclusion as a best-effort stretch goal, not a blocker**: spend at most 30–45 minutes searching (the ACL Anthology page's data availability statement, the paper's supplementary material, a general search for "Context-Agent NTM benchmark github") and if nothing verifiable turns up, proceed with the custom benchmark alone — it is sufficient to answer F0's question on its own, since it was designed specifically to isolate the structural patterns the hypothesis depends on.

---

## 4. Context construction methods to implement

Implement all six as pure functions with the same signature: `build_context(scenario, method, config) -> (selected_turn_ids: list[str], rendered_text: str)`. All methods except full history should be run at **two token budgets** (2048 and 4096) so you can see whether conclusions are sensitive to budget size — treat the budget as a config parameter, not a hardcoded constant.

1. **Full history** — every turn before the query, in chronological order, verbatim. No budget applies (this is deliberately the expensive baseline).
2. **Sliding window** — walk backward from the query, including whole turns until the token budget is reached; never truncate a turn mid-message. Turns dropped are simply omitted.
3. **Rolling summary + recent** — turns that would fall outside the sliding window (per point 2, same budget) are instead collapsed into a single running summary via one LLM call (fixed prompt: *"Summarize the key facts, decisions, and constraints from this conversation excerpt in under 150 words, preserving any specific numbers, names, or rules stated"*), prepended before the verbatim recent-window turns. This is the lossy-compression baseline.
4. **Semantic retrieval** — embed every prior turn (concatenate its `user_message` + `assistant_message`) and the query's `user_message` with the embedding model from §6; rank all prior turns by cosine similarity; include top turns (highest similarity first) until the token budget is reached; then **re-sort the selected turns into chronological order** before rendering (so the model reads them in natural order, not similarity order — this matters and is easy to get wrong).
5. **Oracle single-parent tree** — for the query turn, take `gold_parents[0]` only (by convention, the first listed parent is the "primary" structural parent even on join turns); recursively follow only the primary-parent chain (§5.5's algorithm with `use_primary_only=True`); render the resulting turn set verbatim in chronological order. On non-join scenarios this is usually identical to oracle DAG; the difference shows up specifically on `two_branch_join`, `three_way_join`, and `join_then_split` scenarios, which is the point.
6. **Oracle multi-parent DAG** — full ancestor closure following *all* `gold_parents` recursively (§5.5's algorithm with `use_primary_only=False`); render verbatim in chronological order. No token budget applies (it's whatever the true ancestor closure requires) — this is deliberately the method under test, not a budget-constrained one.

For all six, append the query turn's `user_message` after the rendered context, exactly as the model will see it: `context_text + "\n\nUser: " + query.user_message`.

---

## 5. Definitions used above

### 5.1 Ancestor closure algorithm

```python
def ancestors(query_turn_id, turns_by_id, use_primary_only=False):
    visited = set()
    stack = [query_turn_id]
    while stack:
        tid = stack.pop()
        turn = turns_by_id[tid]
        parents = turn.gold_parents
        if use_primary_only and len(parents) > 1:
            parents = parents[:1]
        for p in parents:
            if p not in visited:
                visited.add(p)
                stack.append(p)
    return visited  # does NOT include query_turn_id itself
```

Render the returned turn IDs sorted by `turn_index` ascending, each as `"User: {user_message}\nAssistant: {assistant_message}\n"`.

### 5.2 Staleness rendering

If a selected turn has `stale: true`, render it with an inline marker rather than silently: `"[Note: the following was later revised — see below]\nUser: ...\nAssistant: ..."`, and ensure the turn named in its `superseded_by` field is also included in the rendered context wherever possible (if it isn't already in the ancestor closure, that's worth flagging as a scenario-construction issue, not silently working around).

---

## 6. Models and configuration

You will need at minimum one strong "response model" to generate answers. Two model classes are strongly preferred (one frontier API model, one open-weight model) because the parent hypothesis specifically expects structured context might help weaker models more than strong ones — but if only one API is configured in this environment, proceed with one and note the limitation explicitly in the final report rather than blocking.

| Role | Default choice | Notes |
|---|---|---|
| Response model A | A current strong Anthropic model (e.g. Claude Sonnet), via `ANTHROPIC_API_KEY` | Temperature 0, fixed system prompt (§7.1). |
| Response model B (optional but preferred) | An open-weight model reachable via whatever API is configured (e.g. Together.ai, Groq, or local Ollama) | Same temperature/prompt discipline. If unavailable, skip and note it. |
| Embedding model | `sentence-transformers/all-mpnet-base-v2`, run locally (no API key needed) | Swap for an API embedding model only if the local model is unavailable in this environment; keep it fixed across the whole run either way. |
| Tokenizer (for all token counts) | `tiktoken`, `cl100k_base` encoding | This is an approximation for non-OpenAI models, but what matters for F0 is that every method is counted the same way, not that the count is exactly what any given provider bills. |
| LLM judge (quality scoring, §7.3) | The strongest model you have access to, ideally a different one from at least one of the response models to reduce self-preference bias | Temperature 0. If only one model is available for everything, use it for judging too, but say so explicitly in the report as a limitation. |

Put all of this in a single `manifest.yaml` at the repo root (see §9) so the whole run is reproducible from one file, and log the exact model identifiers actually used (not just "claude" — the specific dated model string) in every output record.

---

## 7. Metrics

### 7.1 Answer generation protocol

Fixed system prompt for every call, every method, every model (do not vary this):

```
You are a helpful assistant continuing an ongoing conversation. You will be shown
some prior turns of the conversation, followed by the user's latest message.
Respond only to the latest message, using the prior turns as context where relevant.
If the provided context does not contain information you would need to answer
completely, say so explicitly rather than guessing.
```

Temperature 0 (or the lowest available) for every response-model and judge call. Log the full rendered prompt, the raw response, input/output token counts, and latency for every single call — you will want to re-inspect specific instances during error analysis, and re-generating later is more expensive than logging now.

### 7.2 Efficiency metrics

- **Context tokens**: token count of the rendered context (not counting the query message or system prompt) per instance, from the tokenizer in §6.
- **Average Context Tokens (ACT)**: mean context tokens across all scenarios, per method per model.
- **Token reduction %**: `1 - (ACT_method / ACT_full_history)`.
- **Latency**: wall-clock time for context construction (should be near-zero for all methods except rolling summary, which requires an LLM call) and for the answer-generation call, logged separately.

### 7.3 Context-selection metrics (computed directly from annotations — no model call needed)

Let `selected` = the set of turn IDs a method actually included, and `evidence` = the scenario's `evidence_turn_ids`.

- **Context precision** = `|selected ∩ evidence| / |selected|`
- **Context recall** = `|selected ∩ evidence| / |evidence|`
- **Context F1** = harmonic mean of precision and recall
- **Context sufficiency** (binary per instance) = `1` if `evidence ⊆ selected`, else `0`; **Context Sufficiency Rate** = mean over all instances for a method
- **Irrelevant Context Ratio** = token count of `(selected \ evidence)` turns ÷ total token count of `selected` turns (token-weighted, not turn-count-weighted — a single huge irrelevant turn should count more than several tiny relevant ones)

Compute all five for every method on every instance. These do not require an LLM call and should be computed first, since they're a cheap sanity check that your context-construction code is correct before you spend money on answer generation (e.g., oracle DAG should have context sufficiency of 1.0 on essentially every instance by construction — if it doesn't, you have a bug, not a finding).

### 7.4 Answer quality metrics (require the LLM judge)

For each `(scenario, method, model)` triple, once the answer has been generated:

1. **Checklist score**: send the judge model the scenario's `answer_checklist` and the generated answer; ask it to return structured JSON marking each checklist item satisfied (`true`/`false`) with a one-sentence justification. Score = fraction of `required: true` items marked satisfied. Fixed judge prompt:

```
You are scoring whether an AI assistant's answer satisfies a checklist of
requirements. For each checklist item, decide TRUE (the answer clearly satisfies
this) or FALSE (it does not, or it's ambiguous/unaddressed). Be strict: an answer
that is vague or only partially addresses a requirement should be FALSE for that
item. Return only JSON: [{"id": "...", "satisfied": true|false, "reason": "..."}]

Checklist:
{checklist_json}

Assistant's answer:
{answer_text}
```

2. **Distractor leakage** (binary): does the answer incorporate or assert something specific to a `distractor_turn_ids` turn as if it were relevant to the query? Ask the judge this directly as an additional structured field, giving it the distractor turns' content, not just their IDs.
3. Aggregate: mean checklist score and distractor leakage rate per `(method, model)` across all scenarios, and separately broken down by `family` — the by-family breakdown is where you'll actually see whether joins, resumes, and knowledge-updates behave differently, which matters more than the single pooled number.

---

## 8. Statistical analysis plan

For every pairwise comparison below, use **paired bootstrap**: resample scenario indices with replacement (same resampled indices applied to both methods being compared, since they're evaluated on identical instances), compute the mean difference in the metric of interest per resample, run 10,000 resamples, report the mean difference and its 95% CI (2.5th/97.5th percentile of the resampled differences). Do this separately for each response model — do not pool across models.

Mandatory comparisons (oracle DAG is the system under test):

- Oracle DAG vs. full history — quality and tokens
- Oracle DAG vs. sliding window (both budgets) — quality and tokens
- Oracle DAG vs. rolling summary (both budgets) — quality and tokens
- Oracle DAG vs. semantic retrieval (both budgets) — quality and tokens
- Oracle DAG vs. oracle single-parent tree — quality only, and **specifically filtered to the join-family scenarios** (`two_branch_join`, `three_way_join`, `join_then_split`) since that's the only place a difference should appear

Produce:

1. A per-instance results table (one row per scenario × method × model) with every metric from §7 — this is your raw data, keep it.
2. An aggregated summary table (one row per method × model) with mean/median for every metric plus 95% CI.
3. A **Pareto frontier plot**: x-axis = average context tokens (log scale), y-axis = mean checklist score, one point per method per model, methods labeled. This single plot is the most important output of F0 — it's what a reader (or your future self) will look at first.
4. A by-family breakdown table for checklist score and context recall, so you can see exactly which scenario families the oracle graph helps or fails on.
5. A short failure-case log: list every instance where oracle DAG's context sufficiency was 0 (should be rare/never — investigate each one as a likely scenario-construction bug) and every instance where full history scored equal or higher on checklist score than oracle DAG (investigate whether this is noise, a checklist-writing problem, or a genuine case where more context helped).

---

## 9. Pre-registered decision thresholds (confirm before running, don't adjust after)

Write these into `manifest.yaml` before the full run:

```yaml
decision_thresholds:
  quality_non_inferiority_margin_pp: 5      # oracle DAG must score within 5 percentage points of full history, or better
  min_token_reduction_pct: 40               # oracle DAG must reduce avg context tokens by at least this much vs full history
  join_advantage_required: true             # oracle DAG must beat oracle tree on join-family checklist score for the DAG to be judged worthwhile
```

At the end of the run, apply this check mechanically and report the result plainly — GO, PIVOT, or STOP, per the parent project's decision procedure — rather than writing a qualitative narrative that avoids committing to one of the three. If it's a borderline call, say that explicitly and show the numbers, but still state which side of the threshold it landed on.

---

## 10. Step-by-step execution plan

1. **Repo scaffold.** Apply §0 first — `LICENSE` (Apache-2.0), `NOTICE`, README with the description, status note, and license-structure paragraph from §0. Then create the structure below. Use Python 3.11+, a virtualenv, and keep dependencies minimal (`anthropic` or equivalent SDK, `sentence-transformers`, `tiktoken`, `numpy`, `pandas`, `matplotlib`, `pyyaml`).
   ```
   f0-oracle-feasibility/
     manifest.yaml
     data/scenarios/*.json
     src/schema.py
     src/context_methods.py
     src/generate_scenarios.py
     src/run_experiment.py
     src/score_quality.py
     src/metrics.py
     src/analyze.py
     results/raw/*.jsonl
     results/scored/*.jsonl
     results/tables/*.csv
     results/plots/*.png
     F0_RESULTS.md
     README.md
   ```
2. **Write `schema.py`**: dataclasses/pydantic models for Turn and Scenario matching §2, plus the validation checks from §3.3 as a callable function.
3. **Write `generate_scenarios.py`** and generate **10 pilot scenarios first** (pick 3–4 families, including at least one `two_branch_join`), run validation, and hand-read all 10. **STOP AND CHECK IN** here — confirm the schema and generation quality look right before scaling to 140.
4. Once approved, generate the remaining scenarios up to the targets in §3.1, validating each as it's produced.
5. **Write `context_methods.py`** implementing all six methods from §4, and `metrics.py` implementing the context-selection metrics from §7.3. Run these against your pilot scenarios and confirm oracle DAG gets context sufficiency = 1.0 and full history gets context recall = 1.0 on every pilot instance (both should be true by construction — if not, fix the bug before proceeding).
6. **Write `run_experiment.py`**: for every scenario × method × model × (budget, where applicable) combination, build context, call the response model, save the raw record (prompt, response, tokens, latency, method, model, scenario_id) to `results/raw/`. **Run this on the pilot set only first** and estimate total cost/time by extrapolation. **STOP AND CHECK IN** with the cost/time estimate for the full run before proceeding.
7. Run the full experiment once approved.
8. **Write `score_quality.py`** implementing the LLM-judge protocol from §7.4. Run it on the pilot set, hand-check 5–10 judge outputs against the actual answers for sanity, then run on the full result set.
9. **Write `analyze.py`** producing every table and the Pareto plot from §8, plus the mechanical decision check from §9.
10. **Fill in `F0_RESULTS.md`** using the template in §11 with the actual numbers, tables, and plot. Do not editorialize past what the numbers show; state the GO/PIVOT/STOP result plainly and explain it with the specific comparisons that drove it.

---

## 11. Final report template (`F0_RESULTS.md`)

```markdown
# F0 Oracle Feasibility — Results

Run date: ...
Manifest: (link/commit hash of manifest.yaml used)
Scenario count: ... (by family: ...)
Models: Response A = ..., Response B = ..., Judge = ..., Embedding = ...

## Headline result
[GO / PIVOT / STOP], per the thresholds in manifest.yaml §9.

## Summary table
(method × model: ACT, token reduction %, checklist score, context precision/recall/F1,
sufficiency rate, irrelevant context ratio, distractor leakage rate)

## Pareto frontier
(embed results/plots/pareto.png)

## Mandatory pairwise comparisons
(oracle DAG vs. each baseline, mean difference + 95% CI, quality and tokens)

## Join-specific result (oracle DAG vs. oracle tree, join families only)
(this is the single most important secondary result — does the DAG earn its complexity?)

## By-family breakdown
(table: family × checklist score × context recall, per method)

## Failure cases
(list of flagged instances per §8 point 5, with brief notes)

## Limitations of this run
(model coverage, NTM inclusion or not, judge model overlap with response model, anything
that should qualify how far this result generalizes)

## Recommendation
(what the ordered decision procedure says to do next — proceed to F0.5 candidate-realism
check, pivot the dependency semantics, simplify to tree-only, or stop — stated as the
mechanical output of the thresholds, not a new judgment call)
```

---

## 12. After F0: what "moving on" means (do not start this yet)

If F0 returns GO, the next step in the parent project's plan is **F0.5**, a candidate-realism check: the oracle above assumes the correct parent set is handed to you directly, but a real system has to *find* it inside a large candidate pool first. F0.5 tests whether that finding step (candidate generation) is itself the bottleneck, before any automatic LLM router gets built. That is a separate, smaller follow-on task with its own handoff spec — do not start building an automatic router directly off a GO result from F0 alone; the candidate-recall risk is exactly what F0 does not test.

If F0 returns PIVOT or STOP, do not proceed to F0.5 or any router work — report the result and the specific numbers that drove it, and treat it as a real, publishable finding about where structural context does and doesn't help, not as a failed run to quietly retry with different thresholds.
