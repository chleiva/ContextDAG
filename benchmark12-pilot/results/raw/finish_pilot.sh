#!/bin/sh
cd /Users/chleiva/code/ContextDAG/benchmark12-pilot
until grep -qE "PILOT_DONE|GATE_STOP" results/raw/pipeline_pilot.log; do sleep 120; done
cd /Users/chleiva/code/ContextDAG
git add -A
if grep -q PILOT_DONE benchmark12-pilot/results/raw/pipeline_pilot.log; then
  msg="Benchmark 1.2 Stage A pilot: 40 long scenarios (1.2-pilot), four arms x three responders, Llama-judged, gate applied; claude/BENCHMARK_1.2_PILOT_RESULTS.md"
else
  msg="Benchmark 1.2 Stage A pilot: generation complete; stopped at the first-attempt cosine gate (handoff §3) before answers"
fi
git commit -q -m "$msg

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EivYy2RV14n4jdmboAjxj6" && git tag -f 1.2-pilot && git push -q origin main && git push -q -f origin 1.2-pilot
echo "FINISH_DONE $(date '+%H:%M')"
