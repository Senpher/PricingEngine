PY = uv run python

.PHONY: setup format lint test run-example

setup:
uv venv
uv sync

format:
uv run black src tests

lint:
uv run ruff check .
uv run black --check src tests
uv run mypy src

test:
uv run pytest -q

run-example:
uv run python -m pricingengine.examples.price_irs

