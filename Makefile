# retrieval-hub developer Makefile
#
# These targets cover the core library only. Peer components (mcp, ui, auth,
# cli) will carry their own Makefiles in their own subdirectories in future
# steps per docs/PLATFORM_COMPONENT_PATTERN.md.

PYTHON ?= python3
PIP    ?= pip

.PHONY: help install test test-cov migrate migrate-down format lint clean

help:
	@echo "retrieval-hub core library targets:"
	@echo "  install       install the package in editable mode with dev extras"
	@echo "  test          run pytest"
	@echo "  test-cov      run pytest with coverage"
	@echo "  migrate       alembic upgrade head"
	@echo "  migrate-down  alembic downgrade -1"
	@echo "  format        ruff format"
	@echo "  lint          ruff check + mypy"
	@echo "  clean         remove caches and build artifacts"

install:
	$(PIP) install -e ".[dev]"

test:
	pytest

test-cov:
	pytest --cov=src/retrieval_hub --cov-report=term-missing --cov-report=html

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

format:
	ruff format src tests

lint:
	ruff check src tests
	mypy src

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
