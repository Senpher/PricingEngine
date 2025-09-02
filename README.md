# PricingEngine

Tiny educational project showing how to build and price a vanilla
interest‑rate swap using [QuantLib](https://www.quantlib.org/).

## Quickstart

The project uses [uv](https://github.com/astral-sh/uv) for dependency
management.

```bash
uv venv              # create virtualenv
uv sync              # install deps and the package itself
uv run pytest -q     # run tests
```

To format, lint and type‑check the code:

```bash
make format
make lint
```

## Example

An executable example is provided which prices a 5Y fixed‑vs‑float IRS
on flat curves and prints the MTM and PV01 along with the first cashflow
rows.

```bash
uv run python -m pricingengine.examples.price_irs
```

## Repository layout

```
src/pricingengine/          # package code
├── cashflows/              # fixed and floating leg helpers
├── indices/                # utilities for rate indices
├── instruments/            # common instrument interfaces
├── termstructures/         # curve node container
└── irs.py                  # InterestRateSwap implementation
```

Tests live under `tests/` and can be executed via `make test` or the
`uv run pytest -q` command shown above.

