#!/bin/sh
cd /Users/chleiva/code/ContextDAG/length-ablation
PY=../.venv/bin/python
$PY src/run_ablation.py --stage 1 --workers 4 > results/raw/stage1_answers.log 2>&1
$PY src/run_ablation.py --stage 1 --workers 3 > results/raw/stage1_answers2.log 2>&1
$PY src/judge_ablation.py --workers 6 > results/raw/stage1_judge.log 2>&1
$PY src/judge_ablation.py --workers 3 > results/raw/stage1_judge2.log 2>&1
$PY src/analyze_ablation.py > results/raw/analyze_stage1.log 2>&1
spent=$(F05_ROOT=$PWD $PY ../f05-candidate-realism/src/f05_cost.py | head -1 | sed -E 's/.*spend: \$([0-9.]+).*/\1/')
echo "$(date '+%H:%M') stage 1 done, spend $spent"
if [ "$(echo "$spent < 7" | bc)" = "1" ]; then
  echo "stage 2 gate cleared ($spent < 7)"
  $PY src/run_ablation.py --stage 2 --workers 4 > results/raw/stage2_answers.log 2>&1
  $PY src/run_ablation.py --stage 2 --workers 3 > results/raw/stage2_answers2.log 2>&1
  $PY src/judge_ablation.py --workers 6 > results/raw/stage2_judge.log 2>&1
  $PY src/judge_ablation.py --workers 3 > results/raw/stage2_judge2.log 2>&1
  $PY src/analyze_ablation.py > results/raw/analyze_stage2.log 2>&1
else
  echo "stage 2 SKIPPED (spend $spent >= 7)"
fi
$PY src/write_ablation_report.py > results/raw/report.log 2>&1
cd /Users/chleiva/code/ContextDAG
git add -A && git commit -q -m "Length ablation: Stage 1 (full_history at base/30/60 vs oracle_dag) and Stage 2 (matched-budget retrieval by length), Llama-judged, frozen interpretation applied; claude/LENGTH_ABLATION_RESULTS.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EivYy2RV14n4jdmboAjxj6" && git tag -f length-ablation && git push -q origin main && git push -q -f origin length-ablation
echo "ABLATION_DONE $(date '+%H:%M')"
