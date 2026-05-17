.PHONY: setup demo test dashboard clean

VENV    := .venv
PYTHON  := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
STREAMLIT := $(VENV)/bin/streamlit

## Create virtual environment, install package + dependencies
setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "Setup complete. Copy .env.example to .env and add your API key:"
	@echo "  cp .env.example .env"

## Run the full daily ops cycle (CLI). Use FAST=1 to skip web search.
demo:
	$(PYTHON) run.py --print-report $(if $(FAST),--fast,)

## Run the test suite (no API key needed)
test:
	$(PYTHON) -m pytest tests/ -v

## Launch the Streamlit dashboard
dashboard:
	$(STREAMLIT) run src/ecom_ops/dashboard/app.py

## Remove generated output and Python caches
clean:
	rm -f output/daily_ops_*.md
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
