from __future__ import annotations

import math

import pytest
from QuantLib import (
    Actual365Fixed,
    Annual,
    Continuous,
    Date,
    Days,
    FlatForward,
    January,
    July,
    Months,
    Period,
    QuoteHandle,
    RelinkableQuoteHandle,
    RelinkableYieldTermStructureHandle,
    SavedSettings,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
    ZeroSpreadedTermStructure,
)

from pricingengine.instruments.fx_forward import FXForward
from pricingengine.termstructures.curve_nodes import CurveNodes


def _flat_curve(rate: float, as_of: Date) -> RelinkableYieldTermStructureHandle:
    handle = RelinkableYieldTermStructureHandle()
    handle.linkTo(FlatForward(as_of, rate, Actual365Fixed()))
    return handle


@pytest.fixture
def valuation_date() -> Date:
    return Date(15, January, 2024)


@pytest.fixture(autouse=True)
def _apply_saved_settings(valuation_date: Date):
    with SavedSettings():
        Settings.instance().evaluationDate = valuation_date
        yield


@pytest.fixture
def maturity() -> Date:
    return Date(15, July, 2024)


@pytest.fixture
def notional() -> float:
    return 1_000_000.0


@pytest.fixture
def spot_handle() -> RelinkableQuoteHandle:
    return RelinkableQuoteHandle(SimpleQuote(1.10))


@pytest.fixture
def forward_handle() -> RelinkableQuoteHandle:
    return RelinkableQuoteHandle(SimpleQuote(1.11))


@pytest.fixture
def domestic_curve(valuation_date: Date) -> RelinkableYieldTermStructureHandle:
    return _flat_curve(0.025, valuation_date)


@pytest.fixture
def foreign_curve(valuation_date: Date) -> RelinkableYieldTermStructureHandle:
    return _flat_curve(0.01, valuation_date)


@pytest.fixture
def fx_forward_long(
    maturity: Date,
    notional: float,
    forward_handle: RelinkableQuoteHandle,
    spot_handle: RelinkableQuoteHandle,
    domestic_curve: RelinkableYieldTermStructureHandle,
    foreign_curve: RelinkableYieldTermStructureHandle,
) -> FXForward:
    return FXForward(
        maturity=maturity,
        notional=notional,
        forward_quote=forward_handle,
        spot_quote=spot_handle,
        domestic_curve=domestic_curve,
        foreign_curve=foreign_curve,
        is_long_foreign=True,
    )


@pytest.fixture
def fx_forward_short(
    maturity: Date,
    notional: float,
    forward_handle: RelinkableQuoteHandle,
    spot_handle: RelinkableQuoteHandle,
    domestic_curve: RelinkableYieldTermStructureHandle,
    foreign_curve: RelinkableYieldTermStructureHandle,
) -> FXForward:
    return FXForward(
        maturity=maturity,
        notional=notional,
        forward_quote=forward_handle,
        spot_quote=spot_handle,
        domestic_curve=domestic_curve,
        foreign_curve=foreign_curve,
        is_long_foreign=False,
    )


@pytest.fixture
def domestic_nodes(valuation_date: Date, maturity: Date) -> CurveNodes:
    dates = (
        valuation_date + Period(3, Months),
        valuation_date + Period(5, Months),
        maturity,
    )
    zeros = (0.024, 0.0245, 0.025)
    return CurveNodes.from_zeros(
        as_of=valuation_date,
        dates=dates,
        zeros=zeros,
        day_counter=Actual365Fixed(),
    )


@pytest.fixture
def foreign_nodes(valuation_date: Date, maturity: Date) -> CurveNodes:
    dates = (
        valuation_date + Period(3, Months),
        valuation_date + Period(5, Months),
        maturity,
    )
    zeros = (0.009, 0.0095, 0.01)
    return CurveNodes.from_zeros(
        as_of=valuation_date,
        dates=dates,
        zeros=zeros,
        day_counter=Actual365Fixed(),
    )


# =======================
# A. Construction & validation
# =======================


class TestA_ConstructionAndValidation:
    def test_requires_non_zero_notional(
        self,
        maturity: Date,
        forward_handle: RelinkableQuoteHandle,
        spot_handle: RelinkableQuoteHandle,
        domestic_curve: RelinkableYieldTermStructureHandle,
        foreign_curve: RelinkableYieldTermStructureHandle,
    ) -> None:
        with pytest.raises(ValueError, match="notional must be non-zero"):
            FXForward(
                maturity=maturity,
                notional=0.0,
                forward_quote=forward_handle,
                spot_quote=spot_handle,
                domestic_curve=domestic_curve,
                foreign_curve=foreign_curve,
            )

    def test_invalid_settlement_flag_rejected(
        self,
        maturity: Date,
        notional: float,
        forward_handle: RelinkableQuoteHandle,
        spot_handle: RelinkableQuoteHandle,
        domestic_curve: RelinkableYieldTermStructureHandle,
        foreign_curve: RelinkableYieldTermStructureHandle,
    ) -> None:
        with pytest.raises(ValueError, match="settlement must be"):
            FXForward(
                maturity=maturity,
                notional=notional,
                forward_quote=forward_handle,
                spot_quote=spot_handle,
                domestic_curve=domestic_curve,
                foreign_curve=foreign_curve,
                settlement="delivery",
            )

    def test_requires_linked_curves(
        self,
        maturity: Date,
        notional: float,
        forward_handle: RelinkableQuoteHandle,
        spot_handle: RelinkableQuoteHandle,
        domestic_curve: RelinkableYieldTermStructureHandle,
    ) -> None:
        unlinked = RelinkableYieldTermStructureHandle()
        with pytest.raises(ValueError, match="domestic_curve must be linked"):
            FXForward(
                maturity=maturity,
                notional=notional,
                forward_quote=forward_handle,
                spot_quote=spot_handle,
                domestic_curve=unlinked,
                foreign_curve=domestic_curve,
            )

    def test_numeric_inputs_wrapped_into_handles(
        self,
        maturity: Date,
        notional: float,
        domestic_nodes: CurveNodes,
        foreign_nodes: CurveNodes,
    ) -> None:
        fx = FXForward(
            maturity=maturity,
            notional=notional,
            forward_quote=1.125,
            spot_quote=1.10,
            domestic_curve=domestic_nodes,
            foreign_curve=foreign_nodes,
        )
        assert isinstance(fx.forward_quote, QuoteHandle)
        assert isinstance(fx.spot_quote, QuoteHandle)
        assert isinstance(fx.domestic_curve, YieldTermStructureHandle)
        assert isinstance(fx.foreign_curve, YieldTermStructureHandle)

    def test_from_nodes_matches_handle_constructor(
        self,
        maturity: Date,
        notional: float,
        domestic_nodes: CurveNodes,
        foreign_nodes: CurveNodes,
    ) -> None:
        fx_from_nodes = FXForward.from_nodes(
            maturity=maturity,
            notional=notional,
            forward_rate=1.11,
            spot=1.10,
            domestic_nodes=domestic_nodes,
            foreign_nodes=foreign_nodes,
        )

        fx_direct = FXForward(
            maturity=maturity,
            notional=notional,
            forward_quote=1.11,
            spot_quote=1.10,
            domestic_curve=domestic_nodes.to_handle(),
            foreign_curve=foreign_nodes.to_handle(),
        )

        assert math.isclose(
            fx_from_nodes.mark_to_market(),
            fx_direct.mark_to_market(),
            rel_tol=1e-12,
        )


# =======================
# B. Lifecycle & properties
# =======================


class TestB_LifecycleAndProperties:
    def test_valuation_date_tracks_settings(self, fx_forward_long: FXForward, valuation_date: Date) -> None:
        future_date = valuation_date + Period(10, Days)
        with SavedSettings():
            Settings.instance().evaluationDate = future_date
            fx = fx_forward_long.with_forward(fx_forward_long.forward_rate)
            assert fx.valuation_date == future_date

    def test_is_expired_flag(self, fx_forward_long: FXForward, maturity: Date) -> None:
        assert not fx_forward_long.is_expired
        with SavedSettings():
            Settings.instance().evaluationDate = maturity - Period(1, Days)
            pre_maturity = FXForward(
                maturity=maturity,
                notional=fx_forward_long.notional,
                forward_quote=fx_forward_long.forward_quote,
                spot_quote=fx_forward_long.spot_quote,
                domestic_curve=fx_forward_long.domestic_curve,
                foreign_curve=fx_forward_long.foreign_curve,
            )
            assert not pre_maturity.is_expired

            Settings.instance().evaluationDate = maturity
            on_maturity = FXForward(
                maturity=maturity,
                notional=fx_forward_long.notional,
                forward_quote=fx_forward_long.forward_quote,
                spot_quote=fx_forward_long.spot_quote,
                domestic_curve=fx_forward_long.domestic_curve,
                foreign_curve=fx_forward_long.foreign_curve,
            )
            assert on_maturity.is_expired

            Settings.instance().evaluationDate = maturity + Period(1, Days)
            assert FXForward(
                maturity=maturity,
                notional=fx_forward_long.notional,
                forward_quote=fx_forward_long.forward_quote,
                spot_quote=fx_forward_long.spot_quote,
                domestic_curve=fx_forward_long.domestic_curve,
                foreign_curve=fx_forward_long.foreign_curve,
            ).is_expired

    def test_direction_flag_controls_sign(self, fx_forward_long: FXForward, fx_forward_short: FXForward) -> None:
        pv_long = fx_forward_long.mark_to_market()
        pv_short = fx_forward_short.mark_to_market()
        assert math.isclose(pv_long, -pv_short, rel_tol=1e-12)

        exposure_long = fx_forward_long.currency_exposure()
        exposure_short = fx_forward_short.currency_exposure()
        assert exposure_long["foreign"] == -exposure_short["foreign"]
        assert exposure_long["domestic"] == -exposure_short["domestic"]

    def test_forward_points_consistency(self, fx_forward_long: FXForward) -> None:
        forward_points = fx_forward_long.forward_points()
        assert math.isclose(
            forward_points,
            fx_forward_long.par_forward() - fx_forward_long.spot,
            rel_tol=1e-12,
        )

    def test_currency_exposure_matches_notional(self, fx_forward_long: FXForward) -> None:
        exposure = fx_forward_long.currency_exposure()
        assert exposure["foreign"] == pytest.approx(fx_forward_long.notional)
        assert exposure["domestic"] == pytest.approx(-fx_forward_long.notional * fx_forward_long.forward_rate)


# =======================
# C. Mark-to-market & pricing dynamics
# =======================


class TestC_MarkToMarketAndPricing:
    def test_mark_to_market_matches_interest_rate_parity(self, fx_forward_long: FXForward) -> None:
        fx = fx_forward_long
        df_dom = fx.domestic_discount_factor()
        df_for = fx.foreign_discount_factor()
        fair_forward = fx.spot * df_for / df_dom
        expected = fx.direction * fx.notional * (fair_forward - fx.forward_rate) * df_dom
        assert math.isclose(fx.mark_to_market(), expected, rel_tol=1e-12)
        assert math.isclose(fx.par_forward(), fair_forward, rel_tol=1e-12)

    def test_mtm_zero_when_forward_at_par(self, fx_forward_long: FXForward) -> None:
        par_rate = fx_forward_long.par_forward()
        par_forward = fx_forward_long.with_forward(par_rate)
        assert math.isclose(par_forward.mark_to_market(), 0.0, abs_tol=1e-12)

    def test_mtm_zero_when_expired(self, fx_forward_long: FXForward, maturity: Date) -> None:
        with SavedSettings():
            Settings.instance().evaluationDate = maturity + Period(1, Days)
            assert (
                FXForward(
                    maturity=maturity,
                    notional=fx_forward_long.notional,
                    forward_quote=fx_forward_long.forward_quote,
                    spot_quote=fx_forward_long.spot_quote,
                    domestic_curve=fx_forward_long.domestic_curve,
                    foreign_curve=fx_forward_long.foreign_curve,
                ).mark_to_market()
                == 0.0
            )

    def test_relinking_handles_updates_value(self, fx_forward_long: FXForward) -> None:
        base = fx_forward_long.mark_to_market()

        fx_forward_long.spot_quote.linkTo(SimpleQuote(fx_forward_long.spot + 0.01))
        bumped_spot = fx_forward_long.mark_to_market()
        assert not math.isclose(base, bumped_spot)

        fx_forward_long.spot_quote.linkTo(SimpleQuote(fx_forward_long.spot))
        new_curve = FlatForward(fx_forward_long.valuation_date, 0.03, Actual365Fixed())
        fx_forward_long.domestic_curve.linkTo(new_curve)
        bumped_curve = fx_forward_long.mark_to_market()
        assert not math.isclose(base, bumped_curve)


# =======================
# D. Sensitivities & greeks
# =======================


class TestD_SensitivitiesAndGreeks:
    def test_spot_and_strike_deltas(self, fx_forward_long: FXForward) -> None:
        df_dom = fx_forward_long.domestic_discount_factor()
        df_for = fx_forward_long.foreign_discount_factor()
        assert math.isclose(
            fx_forward_long.spot_delta(),
            fx_forward_long.direction * fx_forward_long.notional * df_for,
            rel_tol=1e-12,
        )
        assert math.isclose(
            fx_forward_long.strike_delta(),
            -fx_forward_long.direction * fx_forward_long.notional * df_dom,
            rel_tol=1e-12,
        )

    def test_deltas_zero_when_expired(self, fx_forward_long: FXForward, maturity: Date) -> None:
        with SavedSettings():
            Settings.instance().evaluationDate = maturity + Period(1, Days)
            expired = FXForward(
                maturity=maturity,
                notional=fx_forward_long.notional,
                forward_quote=fx_forward_long.forward_quote,
                spot_quote=fx_forward_long.spot_quote,
                domestic_curve=fx_forward_long.domestic_curve,
                foreign_curve=fx_forward_long.foreign_curve,
            )
            assert expired.spot_delta() == 0.0
            assert expired.strike_delta() == 0.0

    def test_ir01_domestic_matches_finite_difference(self, fx_forward_long: FXForward) -> None:
        base = fx_forward_long.mark_to_market()

        spread = QuoteHandle(SimpleQuote(1e-4))
        dom_link = fx_forward_long.domestic_curve.currentLink()
        bumped_dom = ZeroSpreadedTermStructure(
            fx_forward_long.domestic_curve,
            spread,
            Continuous,
            Annual,
            dom_link.dayCounter(),
        )
        bumped_df = bumped_dom.discount(fx_forward_long.maturity)
        fair_forward_bumped = fx_forward_long.spot * fx_forward_long.foreign_discount_factor() / bumped_df
        pv_bumped = (
            fx_forward_long.direction
            * fx_forward_long.notional
            * (fair_forward_bumped - fx_forward_long.forward_rate)
            * bumped_df
        )
        expected = (pv_bumped - base) / 1.0
        assert math.isclose(fx_forward_long.ir01_domestic(), expected, rel_tol=1e-10)

    def test_ir01_foreign_matches_finite_difference(self, fx_forward_long: FXForward) -> None:
        base = fx_forward_long.mark_to_market()

        spread = QuoteHandle(SimpleQuote(1e-4))
        for_link = fx_forward_long.foreign_curve.currentLink()
        bumped_for = ZeroSpreadedTermStructure(
            fx_forward_long.foreign_curve,
            spread,
            Continuous,
            Annual,
            for_link.dayCounter(),
        )
        df_for_bumped = bumped_for.discount(fx_forward_long.maturity)
        fair_forward_bumped = fx_forward_long.spot * df_for_bumped / fx_forward_long.domestic_discount_factor()
        pv_bumped = (
            fx_forward_long.direction
            * fx_forward_long.notional
            * (fair_forward_bumped - fx_forward_long.forward_rate)
            * fx_forward_long.domestic_discount_factor()
        )
        expected = (pv_bumped - base) / 1.0
        assert math.isclose(fx_forward_long.ir01_foreign(), expected, rel_tol=1e-10)


# =======================
# E. Cash-flows & reporting utilities
# =======================


class TestE_CashflowsAndReporting:
    def test_cashflow_table_structure(self, fx_forward_long: FXForward) -> None:
        table = fx_forward_long.cashflow_table()
        assert list(table.columns) == [
            "ForeignFlow",
            "DomesticFlow",
            "DF(domestic)",
            "DF(foreign)",
            "Forward(market)",
            "Forward(strike)",
            "PV",
        ]
        assert table.index[0] == fx_forward_long.maturity.ISO()

    def test_cash_settlement_flag_has_no_valuation_effect(self, fx_forward_long: FXForward) -> None:
        cash_settled = FXForward(
            maturity=fx_forward_long.maturity,
            notional=fx_forward_long.notional,
            forward_quote=fx_forward_long.forward_quote,
            spot_quote=fx_forward_long.spot_quote,
            domestic_curve=fx_forward_long.domestic_curve,
            foreign_curve=fx_forward_long.foreign_curve,
            settlement="cash",
        )
        assert math.isclose(
            cash_settled.mark_to_market(),
            fx_forward_long.mark_to_market(),
            rel_tol=1e-12,
        )

    def test_as_dict_contains_serializable_snapshot(self, fx_forward_long: FXForward) -> None:
        payload = fx_forward_long.as_dict()
        assert payload["valuation_date"] == fx_forward_long.valuation_date.ISO()
        assert payload["maturity"] == fx_forward_long.maturity.ISO()
        assert payload["notional"] == fx_forward_long.notional
        assert payload["forward_rate"] == fx_forward_long.forward_rate
        assert payload["spot"] == fx_forward_long.spot
        assert payload["is_long_foreign"] is True
        assert payload["settlement"] == fx_forward_long.settlement


# =======================
# F. Scenario helpers
# =======================


class TestF_ScenarioUtilities:
    def test_with_spot_returns_new_instance(self, fx_forward_long: FXForward) -> None:
        bumped = fx_forward_long.with_spot(fx_forward_long.spot + 0.05)
        assert bumped is not fx_forward_long
        assert bumped.spot == fx_forward_long.spot + 0.05
        assert bumped.forward_rate == fx_forward_long.forward_rate

    def test_with_forward_accepts_handle_or_number(self, fx_forward_long: FXForward) -> None:
        new_forward = fx_forward_long.with_forward(1.15)
        assert math.isclose(new_forward.forward_rate, 1.15)

        handle = RelinkableQuoteHandle(SimpleQuote(1.20))
        new_forward_handle = fx_forward_long.with_forward(handle)
        assert new_forward_handle.forward_quote is handle

    def test_with_notional_scales_currency_exposure(self, fx_forward_long: FXForward) -> None:
        scaled = fx_forward_long.with_notional(2 * fx_forward_long.notional)
        exposure = scaled.currency_exposure()
        assert exposure["foreign"] == pytest.approx(2 * fx_forward_long.notional)
        assert exposure["domestic"] == pytest.approx(-2 * fx_forward_long.notional * fx_forward_long.forward_rate)
