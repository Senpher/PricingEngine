from __future__ import annotations

from dataclasses import dataclass

from QuantLib import (
    AnalyticEuropeanEngine,
    BlackScholesMertonProcess,
    BlackVolTermStructureHandle,
    Date,
    EuropeanExercise,
    Option,
    PlainVanillaPayoff,
    QuoteHandle,
    VanillaOption,
    YieldTermStructureHandle,
)

from .base import MarketLinkedInstrument


@dataclass(frozen=True)
class EuropeanVanillaOptionInstrument(MarketLinkedInstrument):
    """Equity-style European option that reuses QuantLib handles."""

    currency: str
    spot: QuoteHandle
    risk_free_curve: YieldTermStructureHandle
    dividend_curve: YieldTermStructureHandle
    vol_surface: BlackVolTermStructureHandle
    maturity: Date
    strike: float
    option_type: int
    quantity: int = 1
    contract_size: int = 1

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise ValueError("quantity must be non-zero")
        if self.contract_size <= 0:
            raise ValueError("contract_size must be positive")
        if self.option_type not in (Option.Call, Option.Put):
            raise ValueError("option_type must be QuantLib.Option.Call or .Put")
        process = BlackScholesMertonProcess(
            self.spot,
            self.dividend_curve,
            self.risk_free_curve,
            self.vol_surface,
        )
        payoff = PlainVanillaPayoff(self.option_type, self.strike)
        exercise = EuropeanExercise(self.maturity)
        option = VanillaOption(payoff, exercise)
        engine = AnalyticEuropeanEngine(process)
        option.setPricingEngine(engine)
        object.__setattr__(self, "_process", process)
        object.__setattr__(self, "_option", option)
        object.__setattr__(self, "_engine", engine)

    def npv(self) -> float:
        price = self._option.NPV()
        return float(price) * float(self.quantity) * float(self.contract_size)
