#!/bin/sh
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
PY=../.venv/bin/python
export F05_LEDGER=check3
until grep -qE "failures, run spend|STOP:|Traceback" results/raw/check3_minimax.log; do sleep 30; done
until grep -qE "failures, run spend|STOP:|Traceback" results/raw/check3_judge.log; do sleep 30; done
until ! pgrep -f check3_verbosity.py > /dev/null; do sleep 30; done
echo "$(date '+%H:%M') answers + first judge pass done"
# second judge pass: the 580 new MiniMax answers + retries of any failures
$PY src/check3_judge.py --workers 6 > results/raw/check3_judge2.log 2>&1
$PY src/check3_judge.py --workers 3 > results/raw/check3_judge3.log 2>&1
# verbosity: rerun to fill any gaps and write its summary
$PY src/check3_verbosity.py > results/raw/check3_verbosity2.log 2>&1
echo "$(date '+%H:%M') judging done"
$PY src/check3.py > results/raw/check3_analyze.log 2>&1
$PY src/write_check3_report.py > results/raw/check3_report.log 2>&1
cd /Users/chleiva/code/ContextDAG && git add -A && git commit -q -m "Check 3: Llama replication judging, MiniMax baselines + verbosity check, cluster-bootstrap analysis, frontier figure, claude/CHECK3_RESULTS.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EivYy2RV14n4jdmboAjxj6" && git push -q origin main
echo "PIPELINE3_DONE $(date '+%H:%M')"
