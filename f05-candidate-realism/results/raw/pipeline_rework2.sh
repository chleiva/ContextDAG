#!/bin/sh
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
PY=../.venv/bin/python
export F05_LEDGER=check3
until grep -q "REWORK_PIPELINE_DONE" results/raw/pipeline_rework.log; do sleep 30; done
# fill the answers that failed on the pricing lookup, retry item 4's missing call, judge, analyze, write both docs
F05_FORCE_ROUTE=global.anthropic.claude-opus-4-6-v1@us-east-1 $PY src/check3_rejudge_offroute.py > results/raw/rework_offroute2.log 2>&1
$PY src/run_candidate_oracle.py --models response_a,response_b,response_c --workers 4 --extra-methods "semantic_retrieval@512" > results/raw/rework_512_answers2.log 2>&1
$PY src/check3_judge.py --workers 6 > results/raw/rework_512_judge3.log 2>&1
$PY src/check3_judge.py --workers 3 > results/raw/rework_512_judge4.log 2>&1
$PY src/check3.py > results/raw/check3_analyze_rework3.log 2>&1
$PY src/check3_rework.py > results/raw/check3_rework_var.log 2>&1
$PY src/write_check3_report.py > results/raw/check3_report2.log 2>&1
$PY src/write_check3_rework_report.py > results/raw/check3_rework_report.log 2>&1
echo "REWORK2_DONE $(date '+%H:%M')"
