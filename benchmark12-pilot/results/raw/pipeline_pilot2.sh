#!/bin/sh
cd /Users/chleiva/code/ContextDAG/benchmark12-pilot
PY=../.venv/bin/python
until grep -q "FINISH_DONE" results/raw/finish_pilot.log; do sleep 20; done
$PY src/run_pilot.py --precompute > results/raw/precompute.log 2>&1
$PY src/run_pilot.py --workers 4 > results/raw/answers.log 2>&1
$PY src/run_pilot.py --workers 3 > results/raw/answers2.log 2>&1
$PY src/judge_pilot.py --workers 6 > results/raw/judge.log 2>&1
$PY src/judge_pilot.py --workers 3 > results/raw/judge2.log 2>&1
$PY src/analyze_pilot.py > results/raw/analyze.log 2>&1
$PY src/write_pilot_report.py > results/raw/report.log 2>&1
echo "PILOT_DONE $(date '+%H:%M')" >> results/raw/pipeline_pilot.log
cd /Users/chleiva/code/ContextDAG
git add -A && git commit -q -m "Benchmark 1.2 Stage A pilot: 39 long scenarios, four arms x three responders, Llama-judged, frozen gate applied; claude/BENCHMARK_1.2_PILOT_RESULTS.md (proceeded past the first-attempt cosine reading on the user's finish instruction; both readings reported)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EivYy2RV14n4jdmboAjxj6" && git tag -f 1.2-pilot && git push -q origin main && git push -q -f origin 1.2-pilot
echo "PILOT2_DONE $(date '+%H:%M')"
