PYTHON ?= python3
export PYTHONPATH := src

.PHONY: demo trace test verify

demo:
	$(PYTHON) -m believe_engine --seed 7

trace:
	$(PYTHON) -m believe_engine --seed 7 --json

test:
	$(PYTHON) -m unittest discover -s tests -v

verify: test
