PY := .venv/bin/python

.PHONY: setup test lint analyze-f0 analyze-f05 analyze-check3 analyze-pilot analyze-ablation reports

## One-time environment (Python 3.11, uv)
setup:
	uv venv .venv --python 3.11
	uv pip install --python $(PY) -r requirements.lock
	$(PY) -m spacy download en_core_web_sm

## Offline checks: schema validation of every committed scenario, analysis invariants, splice properties
test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

## Re-derive every reported table from the committed raw answers and verdicts. No model calls, no network
## beyond tiktoken's one-time encoding download. Each target regenerates the phase's tables and figures.
analyze-f0:
	cd f0-oracle-feasibility && ../$(PY) src/analyze.py

analyze-f05:
	cd f05-candidate-realism && ../$(PY) src/recall.py && ../$(PY) src/analyze_f05.py

analyze-check3:
	cd f05-candidate-realism && ../$(PY) src/check3.py && ../$(PY) src/check3_rework.py && \
	F05_LEDGER=recalibration ../$(PY) src/recalibrate_judge.py --analyze && \
	F05_LEDGER=recalibration ../$(PY) src/recalibrate_judge.py --analyze --sample-file results/raw/calibration_sample_full.json --suffix _full

analyze-pilot:
	cd benchmark12-pilot && ../$(PY) src/analyze_pilot.py

analyze-ablation:
	cd length-ablation && ../$(PY) src/analyze_ablation.py

## Regenerate the results documents in docs/results from the tables (run the analyze-* targets first)
reports:
	cd f0-oracle-feasibility && ../$(PY) src/write_report.py
	cd f05-candidate-realism && ../$(PY) src/write_report.py && F05_LEDGER=check3 ../$(PY) src/write_check3_report.py && \
	F05_LEDGER=check3 ../$(PY) src/write_check3_rework_report.py && F05_LEDGER=recalibration ../$(PY) src/write_recalibration_report.py
	cd benchmark12-pilot && ../$(PY) src/write_pilot_report.py
	cd length-ablation && ../$(PY) src/write_ablation_report.py
