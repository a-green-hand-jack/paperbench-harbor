.PHONY: install test lint format

install:
	python -m pip install -e '.[dev,datasets]'

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .
