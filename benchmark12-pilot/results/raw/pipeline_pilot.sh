#!/bin/sh
cd /Users/chleiva/code/ContextDAG/benchmark12-pilot
PY=../.venv/bin/python
until grep -qE "failures, run spend|STOP:" results/raw/generate_all.log; do sleep 60; done
# one retry pass for any scenario that failed all attempts (resumable: existing files are skipped)
$PY src/generate_long.py --all --workers 3 > results/raw/generate_retry.log 2>&1
echo "$(date '+%H:%M') generation done: $(ls data/scenarios | wc -l) scenarios"
$PY src/gate_check.py > results/raw/gate_check.log 2>&1 || { echo "GATE_STOP $(date '+%H:%M')"; cat results/raw/gate_check.log; exit 0; }
$PY src/run_pilot.py --precompute > results/raw/precompute.log 2>&1
$PY src/run_pilot.py --workers 4 > results/raw/answers.log 2>&1
$PY src/run_pilot.py --workers 3 > results/raw/answers2.log 2>&1
$PY src/judge_pilot.py --workers 6 > results/raw/judge.log 2>&1
$PY src/judge_pilot.py --workers 3 > results/raw/judge2.log 2>&1
$PY src/analyze_pilot.py > results/raw/analyze.log 2>&1
$PY src/write_pilot_report.py > results/raw/report.log 2>&1
echo "PILOT_DONE $(date '+%H:%M')"
