# PricingEngine

PricingEngine is a Python library for pricing basic financial instruments on top of [QuantLib](https://www.quantlib.org/). It provides building blocks for term structures, cash flows and instruments so you can prototype analytic valuations.

## Features

- Curve representation through `CurveNodes` for discounting and forecasting.
- Cash flow modeling of fixed and floating legs.
- Instruments including interest rate swaps, FX forwards, swaptions and equity options.
- Helpers to compute MTM, PV01/DV01 and cash flow tables.

## Installation

This project targets Python 3.11+. Install the package and test dependencies with:

```bash
pip install -e .[test]
```

## Example

Run the built-in example to price a vanilla interest rate swap:

```bash
python -m pricingengine.examples.price_irs
```

The script builds flat discount and forecast curves, calculates MTM and PV01 and prints the cash-flow schedule.

## Development

Formatting and linting are managed via `ruff`, `black` and `mypy`. Helpful `make` targets:

```bash
make format   # format code
make lint     # ruff, black --check and mypy
make test     # run pytest
```

## License

Made With Love <3
