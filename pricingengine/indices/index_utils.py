"""Helpers for working with rate indices."""

from __future__ import annotations

from QuantLib import Euribor6M, Index, Months, Period, Simple, USDLibor

from pricingengine.structures.curve_nodes import CurveNodes


def make_forecast_index(name: str, forecast_nodes: CurveNodes) -> Index:
    """Create an Ibor-like index linked to the supplied forecast curve."""

    handle = forecast_nodes.to_handle()
    key = name.lower()
    if "eur" in key:
        index: Index = Euribor6M(handle)
    elif "usd" in key or "libor" in key:
        index = USDLibor(Period(6, Months), handle)
    else:
        # default to Euribor6M when unsure
        index = Euribor6M(handle)

    fixing_date = index.fixingDate(forecast_nodes.asof)
    rate = handle.forwardRate(
        forecast_nodes.asof,
        forecast_nodes.asof + index.tenor(),
        index.dayCounter(),
        Simple,
    ).rate()
    index.addFixing(fixing_date, rate)
    return index


__all__ = ["make_forecast_index"]
