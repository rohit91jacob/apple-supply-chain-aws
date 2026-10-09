# Developer entrypoints. `make help` lists targets. Settings come from .env when present.
-include .env
export

UV ?= uv
FIXTURES_DIR ?= data/fixtures-build
TF_DIR := infra/envs/dev

.DEFAULT_GOAL := help
.PHONY: help install lint format test test-unit test-e2e test-live fixtures pipeline pipeline-fixtures \
        extract silver marts graph dq verify report dbt-build dbt-compile-athena sec-fixtures \
        tf-fmt tf-validate tf-lint tf-checkov infra-check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Create the virtualenv (pinned by uv.lock)
	$(UV) sync --frozen --all-groups

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Auto-fix lint and format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test: ## Unit + end-to-end tests (offline; two processes, see docs/runbook.md)
	$(UV) run pytest tests/unit --cov --cov-report=
	$(UV) run pytest -m e2e tests/e2e --cov --cov-append --cov-report=term

test-unit: ## Unit tests only
	$(UV) run pytest tests/unit

test-e2e: ## End-to-end pipeline on fixtures, rerun idempotency and DQ-failure path
	$(UV) run pytest -m e2e tests/e2e

test-live: ## Live checks against the real public sources (network)
	$(UV) run pytest -m live tests/integration/test_live_sources.py

fixtures: ## Assemble offline fixtures (real SEC + SYNTHETIC supplier PDFs / Comtrade) into FIXTURES_DIR
	$(UV) run asc fixtures --out $(FIXTURES_DIR)

pipeline-fixtures: fixtures ## Full Step Functions pipeline offline on fixtures
	ASC_SOURCE_MODE=fixtures ASC_FIXTURES_DIR=$(FIXTURES_DIR) ASC_TRADE_YEARS=2022-2024 \
	ASC_DATA_DIR=data/fixtures-run $(UV) run asc pipeline

pipeline: ## Full pipeline on the real sources (downloads; set ASC_DATA_DIR outside the repo)
	$(UV) run asc pipeline

extract: ## Download every source into the raw bucket
	$(UV) run asc extract

silver: ## raw -> silver Iceberg tables
	$(UV) run asc silver

marts: ## silver -> DuckDB -> dbt build -> gold Iceberg
	$(UV) run asc marts

graph: ## supplier network graph + disruption scenarios + Neptune CSVs
	$(UV) run asc graph

dq: ## All data-quality checks (exit 3 on error-level failures)
	$(UV) run asc dq

verify: ## Reconcile outputs with Apple's published Q4 statements (downloads the PDFs)
	$(UV) run asc verify

report: ## Write the static results site to ./site (open site/index.html)
	$(UV) run asc report --out site

dbt-build: ## dbt build against the current DuckDB warehouse
	cd dbt && $(UV) run dbt build --profiles-dir . --target $${DBT_TARGET:-dev}

dbt-compile-athena: ## Compile the dbt project for the Athena target (no connection)
	$(UV) run --group athena python scripts/dbt_compile_athena.py

sec-fixtures: ## Rebuild the committed real SEC fixtures from a live raw zone
	$(UV) run python scripts/make_sec_fixtures.py --data-dir $(ASC_DATA_DIR)

tf-fmt: ## terraform fmt -check
	terraform -chdir=infra fmt -check -recursive

tf-validate: ## terraform init (no backend) + validate
	terraform -chdir=$(TF_DIR) init -backend=false -input=false
	terraform -chdir=$(TF_DIR) validate

tf-lint: ## tflint (AWS ruleset)
	cd infra && tflint --init && tflint --recursive --config "$$(pwd)/.tflint.hcl"

tf-checkov: ## checkov static analysis of the Terraform
	uvx --from "checkov==3.3.26" checkov -d infra --framework terraform --quiet --compact

infra-check: tf-fmt tf-validate tf-lint tf-checkov ## Every Terraform check CI runs

clean: ## Remove local caches and build outputs (not downloaded data outside the repo)
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov site dbt/target dbt/logs data/fixtures-*
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
