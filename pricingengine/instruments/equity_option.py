from __future__ import annotations

from dataclasses import dataclass

from QuantLib import (
    TARGET,
    Actual365Fixed,
    AnalyticEuropeanEngine,
    BlackConstantVol,
    BlackScholesMertonProcess,
    BlackVolTermStructureHandle,
    Date,
    EuropeanExercise,
    FlatForward,
    Option,
    PlainVanillaPayoff,
    QuoteHandle,
    SimpleQuote,
    VanillaOption,
    YieldTermStructureHandle,
)

from pricingengine.instruments._instrument import Instrument


@dataclass(frozen=True, kw_only=True, slots=True)
class EquityOption(Instrument):
    """Vanilla European equity option priced via Black--Scholes."""

    valuation_date: Date
    maturity: Date
    option_type: str  # 'call' or 'put'
    strike: float
    spot: float
    volatility: float  # absolute vol (e.g. 0.20)
    risk_free_rate: float  # continuously compounded
    dividend_rate: float = 0.0  # continuous dividend yield

    def is_expired(self) -> bool:
        return self.valuation_date >= self.maturity

    def _option(
        self,
        *,
        spot: float | None = None,
        volatility: float | None = None,
        risk_free_rate: float | None = None,
        dividend_rate: float | None = None,
    ) -> VanillaOption:
        s = QuoteHandle(SimpleQuote(self.spot if spot is None else spot))
        dc = Actual365Fixed()
        r = self.risk_free_rate if risk_free_rate is None else risk_free_rate
        q = self.dividend_rate if dividend_rate is None else dividend_rate
        v = self.volatility if volatility is None else volatility
        r_ts = YieldTermStructureHandle(FlatForward(self.valuation_date, r, dc))
        q_ts = YieldTermStructureHandle(FlatForward(self.valuation_date, q, dc))
        vol_ts = BlackVolTermStructureHandle(
            BlackConstantVol(self.valuation_date, TARGET(), v, dc)
        )
        process = BlackScholesMertonProcess(s, q_ts, r_ts, vol_ts)
        payoff = PlainVanillaPayoff(
            Option.Call if self.option_type.lower() == "call" else Option.Put,
            self.strike,
        )
        exercise = EuropeanExercise(self.maturity)
        opt = VanillaOption(payoff, exercise)
        opt.setPricingEngine(AnalyticEuropeanEngine(process))
        return opt

    def mtm(
        self,
        *,
        spot: float | None = None,
        volatility: float | None = None,
        risk_free_rate: float | None = None,
        dividend_rate: float | None = None,
    ) -> float:
        if self.is_expired():
            return 0.0
        return self._option(
            spot=spot,
            volatility=volatility,
            risk_free_rate=risk_free_rate,
            dividend_rate=dividend_rate,
        ).NPV()

    def delta(self, *, spot: float | None = None) -> float:
        if self.is_expired():
            return 0.0
        return self._option(spot=spot).delta()

    def gamma(self, *, spot: float | None = None) -> float:
        if self.is_expired():
            return 0.0
        return self._option(spot=spot).gamma()

    def vega(self, *, volatility: float | None = None) -> float:
        if self.is_expired():
            return 0.0
        return self._option(volatility=volatility).vega()
