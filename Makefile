PYTHON ?= .venv/bin/python

.PHONY: install test lint check assets models-start models-stop smoke api vm-start vm-stop demo scenarios validator-check
install:
	$(PYTHON) -m pip install -e '.[dev,ml]'
test:
	$(PYTHON) -m pytest -q
lint:
	.venv/bin/ruff check src scripts tests
check: lint test
assets:
	$(PYTHON) scripts/fetch_assets.py --models --engine
models-start:
	$(PYTHON) scripts/models.py start
models-stop:
	$(PYTHON) scripts/models.py stop
smoke:
	$(PYTHON) scripts/smoke_llms.py
api:
	$(PYTHON) -m uvicorn incidentlab.app:app --host 127.0.0.1 --port 8140
demo:
	$(PYTHON) scripts/run_incident.py checkout-01
scenarios:
	$(PYTHON) scripts/evaluate_scenarios.py
validator-check:
	$(PYTHON) scripts/check_validator.py
vm-start:
	limactl start --name=pi412-block2 infra/lima/incidentlab.yaml --tty=false
vm-stop:
	limactl stop pi412-block2
