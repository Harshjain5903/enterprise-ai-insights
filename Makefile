PY ?= .venv/bin/python

.PHONY: install test refresh full report report-offline evals cases check tamper

install:
	python3 -m venv .venv && $(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

refresh:
	$(PY) -m insights.cli refresh

full:
	$(PY) -m insights.cli refresh --full

report:
	$(PY) -m insights.cli report

report-offline:
	$(PY) -m insights.cli report --no-llm --no-log

cases:
	$(PY) evals/make_cases.py

evals:
	$(PY) -m evals.run_evals

check:
	$(PY) -m insights.cli validate

tamper:
	-$(PY) -m insights.cli validate --tamper
