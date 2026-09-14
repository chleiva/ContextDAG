#!/bin/sh
# wait for the answer run and the first scoring pass, then score whatever is left, analyze, report
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
until grep -qE "failures, run spend|Traceback|STOP:" results/raw/answers2.log; do sleep 30; done
until grep -qE "failures, run spend|Traceback|STOP:" results/raw/scores_all.log; do sleep 30; done
../.venv/bin/python src/score_f05.py --workers 6 > results/raw/scores_final.log 2>&1
../.venv/bin/python src/recall.py > results/raw/recall.log 2>&1
../.venv/bin/python src/analyze_f05.py > results/raw/analyze.log 2>&1
../.venv/bin/python src/write_report.py > results/raw/report.log 2>&1
echo PIPELINE_DONE
