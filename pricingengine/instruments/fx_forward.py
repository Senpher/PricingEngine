from __future__ import annotations

from dataclasses import dataclass

from QuantLib import Date

from pricingengine.instruments._instrument import Instrument
from pricingengine.termstructures.curve_nodes import CurveNodes


@dataclass(frozen=True, kw_only=True, slots=True)
class FXForward(Instrument):
    """Simple FX forward priced under interest-rate parity."""

    valuation_date: Date
    maturity: Date
    notional: float  # foreign currency amount
    forward_rate: float  # agreed domestic per unit foreign
    spot: float  # current spot rate

    def is_expired(self) -> bool:
        return self.valuation_date >= self.maturity

    def mtm(
        self,
        domestic_nodes: CurveNodes,
        foreign_nodes: CurveNodes,
        *,
        spot: float | None = None,
    ) -> float:
        if self.is_expired():
            return 0.0
        s = self.spot if spot is None else spot
        df_dom = domestic_nodes.discount_factor(self.maturity)
        df_for = foreign_nodes.discount_factor(self.maturity)
        fwd_mkt = s * df_for / df_dom
        return self.notional * (fwd_mkt - self.forward_rate) * df_dom

    def delta(self, foreign_nodes: CurveNodes) -> float:
        """Sensitivity of PV to a change in the spot rate."""
        if self.is_expired():
            return 0.0
        return self.notional * foreign_nodes.discount_factor(self.maturity)
