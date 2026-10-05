.PHONY: install dev test lint format cov run api clean
install:
	pip install -e .[api]
dev:
	pip install -e .[dev]
test:
	python -m pytest tests -q
cov:
	python -m pytest tests -q --cov=transport_hub --cov-report=term-missing:skip-covered
lint:
	ruff check . && ruff format --check .
format:
	ruff check . --fix && ruff format .
run:
	transport-hub
api:
	transport-hub-api
clean:
	rm -rf workspace/*.parquet workspace/*.pkl workspace/*.json workspace/*.jsonl .pytest_cache
