from __future__ import annotations

from dataclasses import dataclass

from QuantLib import Date, Index, EuropeanExercise, Swaption as QLSwaption, BlackSwaptionEngine

from pricingengine.instruments._instrument import Instrument
from pricingengine.instruments.interest_rate_swap import InterestRateSwap
from pricingengine.structures.curve_nodes import CurveNodes


@dataclass(frozen=True, kw_only=True, slots=True)
class Swaption(Instrument):
    """European swaption on a vanilla interest-rate swap."""

    swap: InterestRateSwap
    exercise_date: Date
    volatility: float  # Black vol

    def is_expired(self) -> bool:
        return self.swap.valuation_date >= self.exercise_date

    def _ql_swaption(
        self,
        forecast_index: Index,
        discount_nodes: CurveNodes,
        volatility: float,
    ) -> QLSwaption:
        vanilla = self.swap._vanilla_swap_ql(forecast_index, discount_nodes)
        exercise = EuropeanExercise(self.exercise_date)
        swpn = QLSwaption(vanilla, exercise)
        engine = BlackSwaptionEngine(discount_nodes.to_handle(), volatility)
        swpn.setPricingEngine(engine)
        return swpn

    def mtm(
        self,
        forecast_index: Index,
        discount_nodes: CurveNodes,
        *,
        volatility: float | None = None,
    ) -> float:
        if self.is_expired():
            return 0.0
        v = self.volatility if volatility is None else volatility
        return self._ql_swaption(forecast_index, discount_nodes, v).NPV()

    def vega(
        self,
        forecast_index: Index,
        discount_nodes: CurveNodes,
        *,
        volatility: float | None = None,
    ) -> float:
        if self.is_expired():
            return 0.0
        v = self.volatility if volatility is None else volatility
        return self._ql_swaption(forecast_index, discount_nodes, v).vega()
