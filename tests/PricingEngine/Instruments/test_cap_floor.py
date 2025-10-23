from __future__ import annotations

import pytest
import QuantLib as ql
from QuantLib import (
    TARGET,
    Actual360,
    Actual365Fixed,
    BlackCapFloorEngine,
    ConstantOptionletVolatility,
    Date,
    DateGeneration,
    ForwardCurve,
    IborIndex,
    ModifiedFollowing,
    OptionletVolatilityStructureHandle,
    Period,
    Preceding,
    SavedSettings,
    Schedule,
    Settings,
    YieldTermStructureHandle,
    ZeroCurve,
)

from PricingEngine.Instruments import Cap, Floor
from PricingEngine.Instruments.Common import CURRENCIES, FloatingLeg


@pytest.fixture
def evaluation_date() -> Date:
    return Date(15, 1, 2024)


@pytest.fixture
def issue_date(evaluation_date: Date) -> Date:
    return evaluation_date


@pytest.fixture
def maturity() -> Date:
    return Date(15, 1, 2026)


@pytest.fixture
def tenor() -> Period:
    return Period("3M")


@pytest.fixture
def nominal() -> float:
    return 100_000_000


@pytest.fixture
def currency() -> str:
    return "SEK"


@pytest.fixture
def calendar():
    return TARGET()


@pytest.fixture
def day_counter():
    return Actual360()


@pytest.fixture
def discount_curve(issue_date, maturity, tenor, calendar, day_counter):
    sched = Schedule(
        issue_date,
        maturity,
        tenor,
        calendar,
        ModifiedFollowing,
        Preceding,
        DateGeneration.Forward,
        False,
    )
    horizon = sched.dates()[-1] + tenor
    zeros = (0.025, 0.025)
    curve = ZeroCurve((issue_date, horizon), zeros, day_counter)
    return YieldTermStructureHandle(curve)


@pytest.fixture
def index(calendar, day_counter, issue_date, maturity, tenor, currency):  # noqa: PLR0913
    sched = Schedule(
        issue_date,
        maturity,
        tenor,
        calendar,
        ModifiedFollowing,
        Preceding,
        DateGeneration.Forward,
        False,
    )
    horizon = sched.dates()[-1] + tenor
    flat_rate = 0.025
    yts = YieldTermStructureHandle(ForwardCurve((issue_date, horizon), (flat_rate, flat_rate), day_counter))

    idx = IborIndex(
        "Libor",
        tenor,
        2,
        CURRENCIES[currency],
        calendar,
        ModifiedFollowing,
        False,
        day_counter,
        yts,
    )
    idx.addFixings(
        tuple(idx.fixingDate(d) for d in sched.dates()),
        tuple(flat_rate for _ in sched.dates()),
        True,
    )
    return idx


@pytest.fixture
def optionlet_vol(calendar):
    vol = ConstantOptionletVolatility(
        0,
        calendar,
        ModifiedFollowing,
        0.20,
        Actual365Fixed(),
    )
    return OptionletVolatilityStructureHandle(vol)


@pytest.fixture
def floating_leg(index, calendar, day_counter, issue_date, maturity, tenor, nominal, currency):  # noqa: PLR0913
    def make(gearing: float = 1.0, spread: float = 0.0) -> FloatingLeg:
        return FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            index=index,
            gearing=gearing,
            spread=spread,
        )

    return make


def test_cap_matches_quantlib(evaluation_date, floating_leg, discount_curve, optionlet_vol):
    with SavedSettings():
        Settings.instance().evaluationDate = evaluation_date

        fl = floating_leg()
        cashflows = tuple(fl.cashflows)
        strike = 0.03
        strikes = (strike,) * len(cashflows)

        instrument = Cap(
            floating_leg=fl,
            strike=strikes,
            discount_curve=discount_curve,
            vol=optionlet_vol,
        )

        expected = ql.Cap(list(cashflows), strikes)
        expected.setPricingEngine(BlackCapFloorEngine(discount_curve, optionlet_vol))

        assert instrument.npv() == pytest.approx(expected.NPV(), rel=1e-12)


def test_floor_matches_quantlib(evaluation_date, floating_leg, discount_curve, optionlet_vol):
    with SavedSettings():
        Settings.instance().evaluationDate = evaluation_date

        fl = floating_leg(spread=0.0025)
        cashflows = tuple(fl.cashflows)
        strikes = tuple(0.02 + i * 0.0001 for i in range(len(cashflows)))

        instrument = Floor(
            floating_leg=fl,
            strike=strikes,
            discount_curve=discount_curve,
            vol=optionlet_vol,
        )

        expected = ql.Floor(list(cashflows), strikes)
        expected.setPricingEngine(BlackCapFloorEngine(discount_curve, optionlet_vol))

        assert instrument.npv() == pytest.approx(expected.NPV(), rel=1e-12)


def test_cap_strike_length_validation(evaluation_date, floating_leg, discount_curve, optionlet_vol):
    with SavedSettings():
        Settings.instance().evaluationDate = evaluation_date

        fl = floating_leg()
        cashflows = tuple(fl.cashflows)
        strikes = (0.03,) * (len(cashflows) - 1)

        with pytest.raises(ValueError):
            Cap(
                floating_leg=fl,
                strike=strikes,
                discount_curve=discount_curve,
                vol=optionlet_vol,
            )


def test_expired_floor_returns_zero(maturity, floating_leg, discount_curve, optionlet_vol):
    past_date = maturity + Period("1D")
    with SavedSettings():
        Settings.instance().evaluationDate = past_date

        fl = floating_leg()
        cashflows = tuple(fl.cashflows)
        strikes = (0.02,) * len(cashflows)

        instrument = Floor(
            floating_leg=fl,
            strike=strikes,
            discount_curve=discount_curve,
            vol=optionlet_vol,
        )

        assert instrument.is_expired is True
        assert instrument.npv() == 0.0
