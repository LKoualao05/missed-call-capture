.PHONY: install test lint run simulate

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check app tests scripts

run:
	uvicorn --factory app.main:app_factory --reload --port 8000

simulate:
	python scripts/simulate.py
