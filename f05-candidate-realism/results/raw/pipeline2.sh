#!/bin/sh
# Patient completion: re-run the (resumable) Opus scorer until nothing is left, waiting out the
# global-profile daily token quota between passes; then recall -> analysis -> report.
cd /Users/chleiva/code/ContextDAG/f05-candidate-realism
PY=../.venv/bin/python
pass=1
while true; do
  $PY src/score_f05.py --workers 3 > results/raw/scores_pass$pass.log 2>&1
  left=$($PY -c "
import json
a={json.loads(l)['key'] for l in open('results/raw/answers.jsonl') if l.strip()}
s={json.loads(l)['key'] for l in open('results/scored/scores.jsonl') if l.strip()}
print(len(a-s))")
  echo "$(date '+%H:%M') pass $pass done, $left unscored"
  [ "$left" -eq 0 ] && break
  pass=$((pass+1)); [ $pass -gt 20 ] && { echo "GIVING UP after 20 passes"; break; }
  sleep 1800
done
$PY src/recall.py > results/raw/recall.log 2>&1
$PY src/analyze_f05.py > results/raw/analyze.log 2>&1
$PY src/write_report.py > results/raw/report.log 2>&1
echo PIPELINE_DONE
