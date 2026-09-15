#!/bin/sh
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
PY=../.venv/bin/python
export F05_LEDGER=check3
$PY src/check3_judge.py --workers 6 > results/raw/check3_judge2.log 2>&1
$PY src/check3_judge.py --workers 3 > results/raw/check3_judge3.log 2>&1
$PY src/check3_verbosity.py > results/raw/check3_verbosity2.log 2>&1
echo "$(date '+%H:%M') judging done"
$PY src/check3.py > results/raw/check3_analyze.log 2>&1
$PY src/write_check3_report.py > results/raw/check3_report.log 2>&1
echo "PIPELINE3_DONE $(date '+%H:%M')"
