from __future__ import annotations

from dataclasses import dataclass

import pytest
from QuantLib import (
    Actual365Fixed,
    AnalyticEuropeanEngine,
    BlackConstantVol,
    BlackScholesMertonProcess,
    BlackVolTermStructureHandle,
    Date,
    EuropeanExercise,
    FlatForward,
    NullCalendar,
    PlainVanillaPayoff,
    QuoteHandle,
    SavedSettings,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
)
from QuantLib import (
    Option as QLOption,
)

from PricingEngine.Instruments.Common import Option


@dataclass(frozen=True, kw_only=True)
class CountingOption(Option):
    quantity: int
    strike: float
    expiry: Date
    spot: QuoteHandle
    dividend_curve: YieldTermStructureHandle
    risk_free_curve: YieldTermStructureHandle
    vol: BlackVolTermStructureHandle

    process_builds = 0
    engine_builds = 0

    def _expiry_date(self) -> Date:
        return self.expiry

    @property
    def _payoff(self) -> PlainVanillaPayoff:
        return PlainVanillaPayoff(QLOption.Call, float(self.strike))

    @property
    def _exercise(self) -> EuropeanExercise:
        return EuropeanExercise(self.expiry)

    def _engine(self, process: BlackScholesMertonProcess) -> AnalyticEuropeanEngine:
        type(self).engine_builds += 1
        return AnalyticEuropeanEngine(process)

    def _process(self) -> BlackScholesMertonProcess:
        type(self).process_builds += 1
        return BlackScholesMertonProcess(
            self.spot,
            self.dividend_curve,
            self.risk_free_curve,
            self.vol,
        )


def _flat_term_structure(rate: float) -> YieldTermStructureHandle:
    valuation_date = Settings.instance().evaluationDate
    return YieldTermStructureHandle(FlatForward(valuation_date, rate, Actual365Fixed()))


def _flat_vol(vol: float) -> BlackVolTermStructureHandle:
    valuation_date = Settings.instance().evaluationDate
    return BlackVolTermStructureHandle(BlackConstantVol(valuation_date, NullCalendar(), vol, Actual365Fixed()))


def _make_option() -> CountingOption:
    CountingOption.process_builds = 0
    CountingOption.engine_builds = 0

    settings = Settings.instance()
    valuation_date = settings.evaluationDate
    expiry = valuation_date + 30

    spot = QuoteHandle(SimpleQuote(100.0))
    dividend = _flat_term_structure(0.0)
    risk_free = _flat_term_structure(0.01)
    vol = _flat_vol(0.2)

    return CountingOption(
        quantity=1,
        strike=100.0,
        expiry=expiry,
        spot=spot,
        dividend_curve=dividend,
        risk_free_curve=risk_free,
        vol=vol,
    )


def test_option_reuses_cached_quantlib_objects():
    with SavedSettings():
        Settings.instance().evaluationDate = Date(15, 5, 2024)
        opt = _make_option()

        first = opt.npv_per_unit()
        second = opt.npv_per_unit()

        assert second == pytest.approx(first)
        assert CountingOption.process_builds == 1
        assert CountingOption.engine_builds == 1

        first_delta = opt.delta()
        second_delta = opt.delta()

        assert second_delta == pytest.approx(first_delta)
        assert CountingOption.process_builds == 1
        assert CountingOption.engine_builds == 1

        assert opt._ql_option() is opt._ql_option()
