# PricingEngine

A lightweight derivatives pricing engine built on top of the [QuantLib](https://www.quantlib.org/) Python bindings.

This initial version provides:

- `CurveNodes`: immutable container for curve nodes with convenient bumping utilities.
- `InterestRateSwap`: vanilla single-currency interest rate swap composed of fixed and floating legs.

The package is organised under `src/pricingengine` and targets Python 3.11+.
