from __future__ import annotations

import math

import pytest
import QuantLib as ql

from pricingengine.instruments.fx_forward import FXForward


def _setup_settings(as_of: ql.Date) -> None:
    ql.Settings.instance().evaluationDate = as_of


def _flat_curve(rate: float) -> ql.RelinkableYieldTermStructureHandle:
    today = ql.Settings.instance().evaluationDate
    dc = ql.Actual365Fixed()
    handle = ql.RelinkableYieldTermStructureHandle()
    handle.linkTo(ql.FlatForward(today, rate, dc))
    return handle


@pytest.fixture
def fx_forward() -> FXForward:
    today = ql.Date(15, ql.January, 2024)
    _setup_settings(today)
    maturity = ql.Date(15, ql.July, 2024)

    spot = ql.RelinkableQuoteHandle(ql.SimpleQuote(1.10))
    forward = ql.RelinkableQuoteHandle(ql.SimpleQuote(1.11))
    dom_curve = _flat_curve(0.025)
    for_curve = _flat_curve(0.01)

    return FXForward(
        maturity=maturity,
        notional=1_000_000.0,
        forward_quote=forward,
        spot_quote=spot,
        domestic_curve=dom_curve,
        foreign_curve=for_curve,
        is_long_foreign=True,
    )


def test_mark_to_market_matches_interest_rate_parity(fx_forward: FXForward) -> None:
    maturity = fx_forward.maturity
    dom_curve = fx_forward.domestic_curve
    for_curve = fx_forward.foreign_curve
    spot = fx_forward.spot_quote
    fwd = fx_forward.forward_quote

    df_dom = dom_curve.discount(maturity)
    df_for = for_curve.discount(maturity)
    fair_forward = spot.value() * df_for / df_dom
    expected = fx_forward.notional * (fair_forward - fwd.value()) * df_dom

    assert math.isclose(fx_forward.mark_to_market(), expected, rel_tol=1e-12)
    assert math.isclose(fx_forward.par_forward(), fair_forward, rel_tol=1e-12)


def test_handles_relink_update_value(fx_forward: FXForward) -> None:
    base = fx_forward.mark_to_market()

    fx_forward.spot_quote.linkTo(ql.SimpleQuote(1.12))
    bumped_spot_value = fx_forward.mark_to_market()
    assert not math.isclose(base, bumped_spot_value)

    fx_forward.spot_quote.linkTo(ql.SimpleQuote(1.10))

    dom_curve = fx_forward.domestic_curve
    link = ql.FlatForward(fx_forward.valuation_date, 0.03, ql.Actual365Fixed())
    dom_curve.linkTo(link)
    bumped_curve_value = fx_forward.mark_to_market()
    assert not math.isclose(base, bumped_curve_value)


def test_is_expired_follows_quantlib_settings(fx_forward: FXForward) -> None:
    assert not fx_forward.is_expired
    assert fx_forward.mark_to_market() != 0.0

    ql.Settings.instance().evaluationDate = ql.Date(16, ql.July, 2024)
    assert fx_forward.is_expired
    assert fx_forward.mark_to_market() == 0.0


def test_greeks_and_exposures(fx_forward: FXForward) -> None:
    fx = fx_forward
    df_dom = fx.domestic_discount_factor()
    df_for = fx.foreign_discount_factor()

    expected_delta = fx.notional * df_for
    assert math.isclose(fx.spot_delta(), expected_delta, rel_tol=1e-12)

    expected_strike_delta = -fx.notional * df_dom
    assert math.isclose(fx.strike_delta(), expected_strike_delta, rel_tol=1e-12)

    # Domestic IR01 via finite-differencing
    spread = ql.QuoteHandle(ql.SimpleQuote(1e-4))
    dom_link = fx.domestic_curve.currentLink()
    bumped_dom = ql.ZeroSpreadedTermStructure(
        fx.domestic_curve,
        spread,
        ql.Continuous,
        ql.Annual,
        dom_link.dayCounter(),
    )
    df_dom_bumped = bumped_dom.discount(fx.maturity)
    fair_forward_bumped = fx.spot * fx.foreign_discount_factor() / df_dom_bumped
    pv_bumped = fx.notional * (fair_forward_bumped - fx.forward_rate) * df_dom_bumped
    ir01_expected = (pv_bumped - fx.mark_to_market()) / 1.0
    assert math.isclose(fx.ir01_domestic(), ir01_expected, rel_tol=1e-10)

    for_link = fx.foreign_curve.currentLink()
    bumped_for = ql.ZeroSpreadedTermStructure(
        fx.foreign_curve,
        spread,
        ql.Continuous,
        ql.Annual,
        for_link.dayCounter(),
    )
    df_for_bumped = bumped_for.discount(fx.maturity)
    fair_forward_for = fx.spot * df_for_bumped / fx.domestic_discount_factor()
    pv_bumped_for = fx.notional * (fair_forward_for - fx.forward_rate) * fx.domestic_discount_factor()
    ir01_for_expected = (pv_bumped_for - fx.mark_to_market()) / 1.0
    assert math.isclose(fx.ir01_foreign(), ir01_for_expected, rel_tol=1e-10)

    exposure = fx.currency_exposure()
    assert exposure["foreign"] == pytest.approx(fx.notional)
    assert exposure["domestic"] == pytest.approx(-fx.notional * fx.forward_rate)


def test_cashflow_table_shape(fx_forward: FXForward) -> None:
    table = fx_forward.cashflow_table()
    assert list(table.columns) == [
        "ForeignFlow",
        "DomesticFlow",
        "DF(domestic)",
        "DF(foreign)",
        "Forward(market)",
        "Forward(strike)",
        "PV",
    ]
    assert table.index[0] == fx_forward.maturity.ISO()


def test_scenario_helpers_return_new_instances(fx_forward: FXForward) -> None:
    new = fx_forward.with_spot(1.05)
    assert new.spot != fx_forward.spot
    assert new.forward_rate == fx_forward.forward_rate

    new_forward = fx_forward.with_forward(1.2)
    assert new_forward.forward_rate != fx_forward.forward_rate

    bigger = fx_forward.with_notional(2_000_000.0)
    assert bigger.notional == 2_000_000.0
    assert bigger.spot == fx_forward.spot
