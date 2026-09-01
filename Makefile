# retrieval-hub developer Makefile
#
# These targets cover the core library only. Peer components (mcp, ui, auth,
# cli) will carry their own Makefiles in their own subdirectories in future
# steps per docs/PLATFORM_COMPONENT_PATTERN.md.

PYTHON ?= python3
PIP    ?= pip

.PHONY: help install test test-cov migrate migrate-down format lint clean new-source deploy-embedding-tei deploy-embedding-snowflake

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
	@echo ""
	@echo "source onboarding targets:"
	@echo "  new-source SLUG=<slug>  scaffold a new ingestion script"
	@echo ""
	@echo "embedding model deployment targets:"
	@echo "  deploy-embedding-tei        deploy TEI PubMedBERT (CPU)"
	@echo "  deploy-embedding-snowflake  deploy vLLM Snowflake Arctic (GPU)"
	@echo ""
	@echo "cluster deployment targets:"
	@echo "  deploy-cluster        full platform deploy (infra + services)"
	@echo "  deploy-cluster-infra  infrastructure only (PG, embedding, migrations)"
	@echo "  deploy-secrets        create secrets from env file"
	@echo ""
	@echo "  CONTEXT=<ctx>    (required) OpenShift context"
	@echo "  NAMESPACE=<ns>   (default: retrieval-hub)"
	@echo "  ENV_FILE=<path>  cluster config file (see deploy/env.example)"

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

# --- Source onboarding ----------------------------------------------------------

new-source:
ifndef SLUG
	$(error SLUG is required. Usage: make new-source SLUG=my-data-source)
endif
	$(PYTHON) scripts/new_source.py --slug=$(SLUG) $(if $(NAME),--name="$(NAME)",) $(if $(FAMILY),--family=$(FAMILY),)

# --- Embedding model deployment ------------------------------------------------

NAMESPACE ?= retrieval-hub

deploy-embedding-tei:
	./scripts/deploy-embedding.sh tei-pubmedbert \
		--context=$(CONTEXT) --namespace=$(NAMESPACE)

deploy-embedding-snowflake:
	./scripts/deploy-embedding.sh vllm-snowflake \
		--context=$(CONTEXT) --namespace=$(NAMESPACE)

# --- Cluster deployment -------------------------------------------------------

.PHONY: deploy-cluster deploy-cluster-infra deploy-secrets

deploy-cluster:
ifndef CONTEXT
	$(error CONTEXT is required. Usage: make deploy-cluster CONTEXT=<ctx> [ENV_FILE=deploy/.env])
endif
	./scripts/deploy-platform.sh --context=$(CONTEXT) \
		$(if $(ENV_FILE),--env-file=$(ENV_FILE),) \
		$(if $(filter-out retrieval-hub,$(NAMESPACE)),--project=$(NAMESPACE),)

deploy-cluster-infra:
ifndef CONTEXT
	$(error CONTEXT is required)
endif
	./scripts/deploy-platform.sh --context=$(CONTEXT) --infra-only \
		$(if $(ENV_FILE),--env-file=$(ENV_FILE),) \
		$(if $(filter-out retrieval-hub,$(NAMESPACE)),--project=$(NAMESPACE),)

deploy-secrets:
ifndef CONTEXT
	$(error CONTEXT is required)
endif
	./scripts/deploy-platform.sh --context=$(CONTEXT) --infra-only --skip-build \
		$(if $(ENV_FILE),--env-file=$(ENV_FILE),) \
		$(if $(filter-out retrieval-hub,$(NAMESPACE)),--project=$(NAMESPACE),)
