# retrieval-hub-auth developer Makefile
#
# Peer component of retrieval-hub. Independently buildable; the core library
# is consumed as a dependency where needed, but the auth service has no hard
# import of it today (the core library consumes the validated-identity shape
# instead).

PYTHON ?= python3
PIP    ?= pip
VENV   ?= .venv

.PHONY: help install test test-cov format lint clean run-dev

help:
	@echo "retrieval-hub-auth targets:"
	@echo "  install       create venv and install the package in editable mode with dev extras"
	@echo "  test          run pytest"
	@echo "  test-cov      run pytest with coverage"
	@echo "  format        ruff format"
	@echo "  lint          ruff check + mypy"
	@echo "  run-dev       start uvicorn on localhost:8000 with ephemeral test keys"
	@echo "  clean         remove caches and build artifacts"

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"

install: $(VENV)/bin/activate

test: install
	$(VENV)/bin/pytest

test-cov: install
	$(VENV)/bin/pytest --cov=src/retrieval_hub_auth --cov-report=term-missing --cov-report=html

format: install
	$(VENV)/bin/ruff format src tests

lint: install
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/mypy src

run-dev: install
	$(VENV)/bin/python -m retrieval_hub_auth.main

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
