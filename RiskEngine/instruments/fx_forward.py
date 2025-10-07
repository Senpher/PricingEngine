from __future__ import annotations

from dataclasses import dataclass

from QuantLib import Date, QuoteHandle, YieldTermStructureHandle

from .base import MarketLinkedInstrument


@dataclass(frozen=True)
class FxForwardInstrument(MarketLinkedInstrument):
    """Simple FX forward using QuantLib discount handles."""

    currency: str
    spot: QuoteHandle
    domestic_curve: YieldTermStructureHandle
    foreign_curve: YieldTermStructureHandle
    maturity: Date
    strike: float
    notional: float

    def npv(self) -> float:
        spot_level = float(self.spot.value())
        domestic_df = float(self.domestic_curve.discount(self.maturity))
        foreign_df = float(self.foreign_curve.discount(self.maturity))
        forward = spot_level * foreign_df / domestic_df
        return (forward - self.strike) * self.notional * domestic_df
