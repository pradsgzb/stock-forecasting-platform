.PHONY: install format lint type test test-all audit build validate scenario \
	check release-check dev-up dev-down debug clean

install:
	./scripts/bootstrap.sh

format:
	uv run --locked ruff check --fix src tests
	uv run --locked ruff format src tests

lint:
	uv run --locked ruff check src tests
	uv run --locked ruff format --check src tests

type:
	uv run --locked pyright

test:
	uv run --locked pytest -m "not integration" --cov=stock_predictor --cov-report=term-missing

test-all:
	uv run --locked pytest --cov=stock_predictor --cov-report=term-missing --cov-report=xml

audit:
	mkdir -p .local
	uv export --locked --all-groups --no-hashes --output-file .local/audit-requirements.txt
	uv run --locked pip-audit --requirement .local/audit-requirements.txt

build:
	uv build --locked

validate:
	uv run --locked python scripts/validate-repository.py

scenario:
	./scripts/run-reference-scenario.sh

check: lint type test-all validate build

release-check:
	./scripts/release-check.sh

dev-up:
	./scripts/dev-up.sh

dev-down:
	./scripts/dev-down.sh

debug:
	./scripts/debug-api.sh

clean:
	rm -rf .coverage .pytest_cache .ruff_cache .local build dist htmlcov coverage.xml
