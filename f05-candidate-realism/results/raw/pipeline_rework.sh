#!/bin/sh
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
PY=../.venv/bin/python
export F05_LEDGER=check3
# item 4: 32 forced-route Opus re-judgements
F05_FORCE_ROUTE=global.anthropic.claude-opus-4-6-v1@us-east-1 $PY src/check3_rejudge_offroute.py > results/raw/rework_offroute.log 2>&1
echo "$(date '+%H:%M') item 4 done"
# item 5: semantic_retrieval@512 answers for the three models, then Llama judging (two passes for retries)
$PY src/run_candidate_oracle.py --models response_a,response_b,response_c --workers 4 --extra-methods "semantic_retrieval@512" > results/raw/rework_512_answers.log 2>&1
$PY src/check3_judge.py --workers 6 > results/raw/rework_512_judge.log 2>&1
$PY src/check3_judge.py --workers 3 > results/raw/rework_512_judge2.log 2>&1
echo "$(date '+%H:%M') item 5 done"
$PY src/check3.py > results/raw/check3_analyze_rework2.log 2>&1
echo "REWORK_PIPELINE_DONE $(date '+%H:%M')"
