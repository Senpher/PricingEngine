from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import pytest
from QuantLib import (
    TARGET,
    Actual360,
    Actual365Fixed,
    Calendar,
    CashFlows,
    Date,
    Days,
    FlatForward,
    ModifiedFollowing,
    Period,
    QuoteHandle,
    SavedSettings,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
)

from PricingEngine.Instruments import CrossCurrencySwap
from PricingEngine.Instruments.Common import FixedLeg


@pytest.fixture
def eval_date() -> Date:
    return Date(15, 1, 2024)


@pytest.fixture
def calendar() -> Calendar:
    return TARGET()


@pytest.fixture
def eur_leg(eval_date, calendar) -> FixedLeg:
    return FixedLeg(
        nominal=100_000_000,
        currency="EUR",
        issue_date=eval_date,
        maturity=calendar.advance(eval_date, Period("2Y"), ModifiedFollowing, False),
        tenor=Period("6M"),
        calendar=calendar,
        day_counter=Actual360(),
        rate=0.02,
    )


@pytest.fixture
def usd_leg(eval_date, calendar, eur_leg) -> FixedLeg:
    spot = 1.10
    return FixedLeg(
        nominal=eur_leg.nominal * spot,
        currency="USD",
        issue_date=eval_date,
        maturity=eur_leg.maturity,
        tenor=eur_leg.tenor,
        calendar=calendar,
        day_counter=Actual360(),
        rate=0.03,
    )


def _fx_points(
    eval_date: Date,
    *,
    tenors: Iterable[str],
    spot: float,
    domestic_curve: YieldTermStructureHandle,
    foreign_curve: YieldTermStructureHandle,
) -> list[dict[str, float]]:
    cal = TARGET()
    fixing_days = 2
    points: list[dict[str, float]] = []
    spot_date = cal.advance(eval_date, Period(fixing_days, Days), ModifiedFollowing, False)
    df_d_spot = domestic_curve.discount(spot_date)
    df_f_spot = foreign_curve.discount(spot_date)

    for tenor_str in tenors:
        tenor = Period(tenor_str)
        far_date = cal.advance(spot_date, tenor, ModifiedFollowing, False)
        df_dom = domestic_curve.discount(far_date)
        df_for = foreign_curve.discount(far_date)
        forward = spot * (df_for / df_dom) * (df_d_spot / df_f_spot)
        points.append({"tenor": tenor_str, "points": forward - spot})
    return points


def _par_rate(leg: FixedLeg, curve: YieldTermStructureHandle) -> float:
    test_leg = replace(leg, rate=1.0)
    pv_unit = CashFlows.npv(test_leg.cashflows, curve, False, Settings.instance().evaluationDate)
    df_maturity = curve.discount(leg.maturity)
    if pv_unit == 0:
        raise ValueError("Unable to compute par rate with zero annuity")
    return (1.0 - df_maturity) / (pv_unit / leg.nominal)


def _leg_value(
    leg: FixedLeg,
    curve: YieldTermStructureHandle,
    *,
    pay_leg: bool,
    include_initial: bool = True,
    include_final: bool = True,
) -> float:
    sign = -1.0 if pay_leg else 1.0
    val_date = Settings.instance().evaluationDate
    pv = sign * CashFlows.npv(leg.cashflows, curve, False, val_date)

    schedule_dates = list(leg.schedule.dates())
    nominals = leg.nominals
    if include_initial and schedule_dates:
        date0 = schedule_dates[0]
        if date0 >= val_date:
            pv += sign * nominals[0] * curve.discount(date0)
    if include_final and schedule_dates:
        end_date = schedule_dates[-1]
        if end_date >= val_date:
            pv -= sign * nominals[-1] * curve.discount(end_date)
    return pv


class TestCrossCurrencySwap:
    def test_requires_distinct_currencies(self, eur_leg, eval_date):
        Settings.instance().evaluationDate = eval_date
        spot = QuoteHandle(SimpleQuote(1.0))
        curve = YieldTermStructureHandle(FlatForward(eval_date, 0.02, Actual365Fixed()))

        with pytest.raises(ValueError, match="different currencies"):
            CrossCurrencySwap(
                paying_leg=eur_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": curve},
                fx_spot=spot,
                fx_forward_points=[{"tenor": "6M", "points": 0.0}],
            )

    def test_npv_parity_with_bootstrapped_foreign_curve(self, eval_date, calendar, eur_leg, usd_leg):
        with SavedSettings():
            Settings.instance().evaluationDate = eval_date
            spot = 1.10
            fx_spot = QuoteHandle(SimpleQuote(spot))

            eur_curve = YieldTermStructureHandle(FlatForward(eval_date, 0.02, Actual365Fixed()))
            usd_curve = YieldTermStructureHandle(FlatForward(eval_date, 0.03, Actual365Fixed()))

            fx_points = _fx_points(
                eval_date,
                tenors=("6M", "1Y", "18M", "2Y"),
                spot=spot,
                domestic_curve=eur_curve,
                foreign_curve=usd_curve,
            )

            eur_par = _par_rate(eur_leg, eur_curve)
            usd_par = _par_rate(usd_leg, usd_curve)

            swap = CrossCurrencySwap(
                paying_leg=replace(usd_leg, rate=usd_par),
                receiving_leg=replace(eur_leg, rate=eur_par),
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot,
                fx_forward_points=fx_points,
                collateral_currency="EUR",
            )

            pv = swap.npv()
            spot_date = calendar.advance(eval_date, Period(2, Days), ModifiedFollowing, False)
            conversion = spot * eur_curve.discount(spot_date) / usd_curve.discount(spot_date)
            manual_pay = _leg_value(replace(usd_leg, rate=usd_par), usd_curve, pay_leg=True)
            manual_rec = _leg_value(replace(eur_leg, rate=eur_par), eur_curve, pay_leg=False)
            expected = manual_rec + manual_pay * conversion
            assert pytest.approx(expected, rel=1e-9) == pv

            usd_handle = swap.discount_curves["USD"]
            test_date = calendar.advance(eval_date, Period("18M"), ModifiedFollowing, False)
            assert pytest.approx(usd_curve.discount(test_date), rel=1e-6) == usd_handle.discount(test_date)

    def test_breakdown_reports_leg_pvs(self, eval_date, calendar, eur_leg, usd_leg):
        with SavedSettings():
            Settings.instance().evaluationDate = eval_date
            spot = 1.05
            fx_spot = QuoteHandle(SimpleQuote(spot))
            eur_curve = YieldTermStructureHandle(FlatForward(eval_date, 0.02, Actual365Fixed()))
            usd_curve = YieldTermStructureHandle(FlatForward(eval_date, 0.025, Actual365Fixed()))
            fx_points = _fx_points(
                eval_date,
                tenors=("6M", "1Y"),
                spot=spot,
                domestic_curve=eur_curve,
                foreign_curve=usd_curve,
            )

            swap = CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot,
                fx_forward_points=fx_points,
                collateral_currency="EUR",
            )

            details = swap.npv(breakdown=True)
            assert details["pricing_currency"] == "EUR"
            assert set(details["legs"]) == {"paying", "receiving"}
            assert details["legs"]["paying"]["currency"] == "USD"
            assert details["legs"]["receiving"]["currency"] == "EUR"
            assert (
                pytest.approx(
                    details["legs"]["receiving"]["pv_pricing"] + details["legs"]["paying"]["pv_pricing"], rel=1e-12
                )
                == details["npv"]
            )
