from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from QuantLib import (
    TARGET,
    Actual360,
    Actual365Fixed,
    Calendar,
    CashFlows,
    Date,
    Days,
    JointCalendar,
    ModifiedFollowing,
    Period,
    QuoteHandle,
    SavedSettings,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
    ZeroCurve,
)

from PricingEngine.Instruments import CrossCurrencySwap
from PricingEngine.Instruments.Common import FixedLeg


@pytest.fixture(autouse=True)
def _ql_settings(eval_date: Date):
    with SavedSettings():
        Settings.instance().evaluationDate = eval_date
        yield


@pytest.fixture
def eval_date() -> Date:
    return Date(15, 1, 2024)


@pytest.fixture
def calendar() -> Calendar:
    return TARGET()


@pytest.fixture
def eur_leg(eval_date: Date, calendar: Calendar) -> FixedLeg:
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
def usd_leg(eval_date: Date, calendar: Calendar, eur_leg: FixedLeg) -> FixedLeg:
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


CURVE_NODES: dict[str, list[tuple[str, float]]] = {
    "EUR": [
        ("2D", 0.0092),
        ("1W", 0.0095),
        ("1M", 0.0102),
        ("3M", 0.011),
        ("6M", 0.0115),
        ("9M", 0.0121),
        ("1Y", 0.0128),
        ("18M", 0.0139),
        ("2Y", 0.0146),
        ("3Y", 0.0158),
        ("4Y", 0.0169),
        ("5Y", 0.0178),
        ("6Y", 0.0185),
        ("7Y", 0.0191),
        ("8Y", 0.0196),
        ("9Y", 0.0201),
        ("10Y", 0.0205),
        ("12Y", 0.0212),
        ("15Y", 0.022),
        ("20Y", 0.0231),
        ("25Y", 0.0238),
        ("30Y", 0.0242),
        ("35Y", 0.0246),
        ("40Y", 0.0249),
        ("45Y", 0.0251),
    ],
    "USD": [
        ("2D", 0.0126),
        ("1W", 0.0132),
        ("1M", 0.0139),
        ("3M", 0.0148),
        ("6M", 0.0156),
        ("9M", 0.0164),
        ("1Y", 0.0173),
        ("18M", 0.0186),
        ("2Y", 0.0197),
        ("3Y", 0.0214),
        ("4Y", 0.0226),
        ("5Y", 0.0238),
        ("6Y", 0.0247),
        ("7Y", 0.0253),
        ("8Y", 0.0259),
        ("9Y", 0.0264),
        ("10Y", 0.0268),
        ("12Y", 0.0275),
        ("15Y", 0.0284),
        ("20Y", 0.0293),
        ("25Y", 0.0301),
        ("30Y", 0.0307),
        ("35Y", 0.0311),
        ("40Y", 0.0315),
        ("45Y", 0.0319),
    ],
}


FX_FORWARD_POINTS: tuple[dict[str, float], ...] = (
    {"tenor": "2D", "points": -2.4e-05},
    {"tenor": "1W", "points": -8.3e-05},
    {"tenor": "1M", "points": -0.00038},
    {"tenor": "3M", "points": -0.00109},
    {"tenor": "6M", "points": -0.00231},
    {"tenor": "9M", "points": -0.00362},
    {"tenor": "1Y", "points": -0.00505},
    {"tenor": "18M", "points": -0.00785},
    {"tenor": "2Y", "points": -0.0114},
    {"tenor": "3Y", "points": -0.0186},
    {"tenor": "4Y", "points": -0.0251},
    {"tenor": "5Y", "points": -0.0329},
    {"tenor": "6Y", "points": -0.0406},
    {"tenor": "7Y", "points": -0.0472},
    {"tenor": "8Y", "points": -0.0546},
    {"tenor": "9Y", "points": -0.0612},
    {"tenor": "10Y", "points": -0.0678},
    {"tenor": "12Y", "points": -0.0811},
    {"tenor": "15Y", "points": -0.1017},
    {"tenor": "20Y", "points": -0.1293},
    {"tenor": "25Y", "points": -0.1614},
    {"tenor": "30Y", "points": -0.1962},
    {"tenor": "35Y", "points": -0.2334},
    {"tenor": "40Y", "points": -0.2731},
)


def _build_zero_curve(eval_date: Date, currency: str) -> YieldTermStructureHandle:
    day_counter = Actual365Fixed()
    calendar = TARGET()
    nodes = CURVE_NODES[currency]
    dates: list[Date] = [eval_date]
    rates: list[float] = [nodes[0][1]]
    last_date = eval_date
    for tenor_str, rate in nodes:
        tenor = Period(tenor_str)
        next_date = calendar.advance(eval_date, tenor, ModifiedFollowing, False)
        if next_date <= last_date:
            raise ValueError("Curve nodes must be strictly increasing in tenor")
        dates.append(next_date)
        rates.append(rate)
        last_date = next_date
    return YieldTermStructureHandle(ZeroCurve(dates, rates, day_counter))


@pytest.fixture
def eur_curve(eval_date: Date) -> YieldTermStructureHandle:
    return _build_zero_curve(eval_date, "EUR")


@pytest.fixture
def usd_curve(eval_date: Date) -> YieldTermStructureHandle:
    return _build_zero_curve(eval_date, "USD")


@pytest.fixture
def fx_spot_quote() -> QuoteHandle:
    return QuoteHandle(SimpleQuote(1.10))


@pytest.fixture
def fx_points() -> list[dict[str, float]]:
    return [dict(entry) for entry in FX_FORWARD_POINTS]


@pytest.fixture
def discount_curves_eur_only(eur_curve: YieldTermStructureHandle) -> dict[str, YieldTermStructureHandle]:
    return {"EUR": eur_curve}


@pytest.fixture
def discount_curves_both(
    eur_curve: YieldTermStructureHandle,
    usd_curve: YieldTermStructureHandle,
) -> dict[str, YieldTermStructureHandle]:
    return {"EUR": eur_curve, "USD": usd_curve}


@pytest.fixture
def make_swap(
    eur_leg: FixedLeg,
    usd_leg: FixedLeg,
    fx_spot_quote: QuoteHandle,
    fx_points: list[dict[str, float]],
    discount_curves_eur_only: dict[str, YieldTermStructureHandle],
):
    def factory(**overrides):
        return CrossCurrencySwap(
            paying_leg=overrides.get("paying_leg", usd_leg),
            receiving_leg=overrides.get("receiving_leg", eur_leg),
            discount_curves=overrides.get("discount_curves", discount_curves_eur_only),
            fx_spot=overrides.get("fx_spot", fx_spot_quote),
            fx_forward_points=overrides.get("fx_forward_points", fx_points),
            collateral_currency=overrides.get("collateral_currency", "EUR"),
            pricing_currency=overrides.get("pricing_currency"),
            base_currency_is_collateral=overrides.get("base_currency_is_collateral"),
            exchange_initial_notional=overrides.get("exchange_initial_notional", True),
            exchange_final_notional=overrides.get("exchange_final_notional", True),
        )

    return factory


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


# =======================
# A. Construction & guardrails
# =======================


class TestA_ConstructionAndGuardrails:
    def test_kw_only_positionals_rejected(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
    ):
        with pytest.raises(TypeError):
            CrossCurrencySwap(
                eur_leg,
                usd_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

    def test_dataclass_is_frozen(self, make_swap):
        swap = make_swap()
        with pytest.raises(FrozenInstanceError):
            swap.pricing_currency = "USD"

    def test_requires_distinct_currencies(
        self,
        eur_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
    ):
        with pytest.raises(ValueError, match="different currencies"):
            CrossCurrencySwap(
                paying_leg=eur_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

    def test_legs_must_share_issue_and_maturity(  # noqa: PLR0913
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
        calendar: Calendar,
    ):
        mismatched_issue = replace(usd_leg, issue_date=calendar.advance(usd_leg.issue_date, Period("1M")))
        with pytest.raises(ValueError, match="issue date"):
            CrossCurrencySwap(
                paying_leg=mismatched_issue,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve, "USD": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

        mismatched_maturity = replace(usd_leg, maturity=calendar.advance(usd_leg.maturity, Period("1M")))
        with pytest.raises(ValueError, match="maturity"):
            CrossCurrencySwap(
                paying_leg=mismatched_maturity,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve, "USD": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

    def test_pricing_currency_must_match_leg(self, make_swap):
        with pytest.raises(ValueError, match="pricing_currency"):
            make_swap(pricing_currency="GBP")

    def test_missing_pricing_curve_raises(self, make_swap, discount_curves_both):
        curves = {"USD": discount_curves_both["USD"]}
        with pytest.raises(ValueError, match="pricing currency 'EUR'"):
            make_swap(discount_curves=curves)

    def test_missing_collateral_curve_raises(self, make_swap, discount_curves_both):
        curves = {"EUR": discount_curves_both["EUR"]}
        with pytest.raises(ValueError, match="collateral currency 'USD'"):
            make_swap(
                collateral_currency="USD",
                discount_curves=curves,
            )

    def test_discount_curve_keys_must_be_currency_strings(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
        eur_curve: YieldTermStructureHandle,
    ):
        with pytest.raises(ValueError, match="currency codes"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={1: eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

    def test_discount_curve_values_must_be_handles(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
    ):
        with pytest.raises(ValueError, match="YieldTermStructureHandle"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": object()},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )

    def test_rejects_non_positive_fx_spot(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_points: list[dict[str, float]],
    ):
        bad_spot = QuoteHandle(SimpleQuote(-1.0))
        with pytest.raises(ValueError, match="positive"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=bad_spot,
                fx_forward_points=fx_points,
            )

    def test_fx_points_must_not_be_empty(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
    ):
        with pytest.raises(ValueError, match="at least one"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=[],
            )

    def test_fx_points_entries_require_tenor_and_points(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
    ):
        with pytest.raises(ValueError, match="provide 'tenor' and 'points'"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=[{"tenor": "6M"}],
            )

    def test_fx_points_entries_must_be_mappings(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        eur_curve: YieldTermStructureHandle,
        fx_spot_quote: QuoteHandle,
    ):
        with pytest.raises(ValueError, match="must be mappings"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": eur_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=[("6M", 0.0)],
            )


# =======================
# B. Timeline & identity semantics
# =======================


class TestB_TimelineAndIdentity:
    def test_valuation_date_tracks_settings(self, make_swap, calendar: Calendar):
        swap = make_swap()
        assert swap.valuation_date == Settings.instance().evaluationDate

        new_date = calendar.advance(swap.valuation_date, Period("3M"), ModifiedFollowing, False)
        Settings.instance().evaluationDate = new_date
        assert swap.valuation_date == new_date

    def test_is_expired_reflects_maturity(self, make_swap, calendar: Calendar, eur_leg: FixedLeg):
        swap = make_swap()
        assert not swap.is_expired

        past_maturity = calendar.advance(eur_leg.maturity, Period("1D"))
        Settings.instance().evaluationDate = past_maturity
        assert swap.is_expired

    def test_joint_calendar_combines_leg_calendars(self, make_swap, eur_leg: FixedLeg, usd_leg: FixedLeg):
        swap = make_swap()
        expected = JointCalendar(eur_leg.calendar, usd_leg.calendar)
        assert swap.joint_calendar.name() == expected.name()

    def test_npv_zero_when_expired(self, make_swap, calendar: Calendar, eur_leg: FixedLeg):
        swap = make_swap()
        Settings.instance().evaluationDate = calendar.advance(eur_leg.maturity, Period("1D"))

        assert swap.is_expired
        assert swap.npv() == 0.0
        breakdown = swap.npv(breakdown=True)
        assert breakdown["npv"] == 0.0
        assert breakdown["legs"] == {}


# =======================
# C. Currency resolution & conversion factors
# =======================


class TestC_CurrencyResolutionAndConversion:
    def test_default_currency_resolution(self, make_swap):
        swap = make_swap()
        assert swap.pricing_currency == "EUR"
        assert swap.collateral_currency == "EUR"
        assert swap.foreign_currency == "USD"
        assert swap.base_currency_is_collateral is False

    def test_collateral_override_and_base_flag(self, make_swap, discount_curves_both):
        swap = make_swap(collateral_currency="USD", discount_curves=discount_curves_both)
        assert swap.collateral_currency == "USD"
        assert swap.foreign_currency == "USD"
        assert swap.base_currency_is_collateral is True

    def test_base_currency_override_respected(self, make_swap, discount_curves_both):
        swap = make_swap(
            collateral_currency="USD",
            discount_curves=discount_curves_both,
            base_currency_is_collateral=False,
        )
        assert swap.base_currency_is_collateral is False

    def test_conversion_factor_for_pricing_currency_is_unity(self, make_swap):
        swap = make_swap()
        assert swap._conversion_factor_for("EUR") == pytest.approx(1.0)

    def test_conversion_factor_for_foreign_currency_matches_spot_factor(
        self,
        make_swap,
        eur_leg: FixedLeg,
    ):
        swap = make_swap()
        spot_factor = swap._spot_conversion_factor
        expected = swap._conversion_factor_for("USD")
        assert expected == pytest.approx(spot_factor)

    def test_conversion_factor_unknown_currency_errors(self, make_swap):
        swap = make_swap()
        with pytest.raises(ValueError, match="No conversion available"):
            swap._conversion_factor_for("GBP")


# =======================
# D. FX data normalisation & curve coverage
# =======================


class TestD_FxDataAndCurves:
    def test_fx_points_sorted_and_normalised(self, make_swap):
        swap = make_swap(
            fx_forward_points=[
                {"tenor": Period("18M"), "points": 0.001},
                {"tenor": "1M", "points": 0.0005},
                {"tenor": "6M", "points": 0.0007},
            ]
        )
        tenors = [pt[0] for pt in swap.fx_forward_points]
        assert tenors == [Period("1M"), Period("6M"), Period("18M")]

    def test_bootstraps_foreign_curve_when_missing(self, make_swap):
        swap = make_swap()
        assert "USD" in swap.discount_curves

    def test_provided_foreign_curve_preserved(self, make_swap, discount_curves_both, usd_curve):
        swap = make_swap(discount_curves=discount_curves_both)
        assert swap.discount_curves["USD"] is usd_curve

    def test_ensure_handle_requires_horizon_coverage(
        self,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        fx_spot_quote: QuoteHandle,
        fx_points: list[dict[str, float]],
        calendar: Calendar,
    ):
        short_date = calendar.advance(eur_leg.issue_date, Period("6M"))
        short_curve = YieldTermStructureHandle(
            ZeroCurve([eur_leg.issue_date, short_date], [0.02, 0.02], Actual365Fixed())
        )
        with pytest.raises(ValueError, match="discount curve for EUR"):
            CrossCurrencySwap(
                paying_leg=usd_leg,
                receiving_leg=eur_leg,
                discount_curves={"EUR": short_curve},
                fx_spot=fx_spot_quote,
                fx_forward_points=fx_points,
            )


# =======================
# E. Notional exchange toggles & leg PV composition
# =======================


class TestE_NotionalExchangeAndLegPV:
    def test_initial_exchange_toggle_impacts_pv(
        self,
        make_swap,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
    ):
        swap_with = make_swap(exchange_initial_notional=True)
        swap_without = make_swap(exchange_initial_notional=False)

        df_rec_initial = swap_with.discount_curves["EUR"].discount(eur_leg.schedule.dates()[0])
        df_pay_initial = swap_with.discount_curves["USD"].discount(usd_leg.schedule.dates()[0])
        conversion = swap_with._conversion_factor_for("USD")

        expected_diff = eur_leg.nominal * df_rec_initial - usd_leg.nominal * df_pay_initial * conversion
        actual_diff = swap_with.npv() - swap_without.npv()
        assert actual_diff == pytest.approx(expected_diff, rel=1e-12)

    def test_final_exchange_toggle_impacts_pv(
        self,
        make_swap,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
    ):
        swap_with = make_swap(exchange_final_notional=True)
        swap_without = make_swap(exchange_final_notional=False)

        end_date = eur_leg.schedule.dates()[-1]
        df_rec_final = swap_with.discount_curves["EUR"].discount(end_date)
        df_pay_final = swap_with.discount_curves["USD"].discount(end_date)
        conversion = swap_with._conversion_factor_for("USD")

        expected_diff = -eur_leg.nominal * df_rec_final + usd_leg.nominal * df_pay_final * conversion
        actual_diff = swap_with.npv() - swap_without.npv()
        assert actual_diff == pytest.approx(expected_diff, rel=1e-12)

    def test_past_initial_exchange_is_ignored(self, make_swap, calendar: Calendar):
        first_date = make_swap().receiving_leg.schedule.dates()[0]
        Settings.instance().evaluationDate = calendar.advance(first_date, Period(1, Days))

        swap_with = make_swap(exchange_initial_notional=True)
        swap_without = make_swap(exchange_initial_notional=False)
        assert swap_with.npv() == pytest.approx(swap_without.npv(), rel=1e-12)


# =======================
# F. Mark-to-market parity & symmetry
# =======================


class TestF_MarkToMarketParityAndSymmetry:
    def test_npv_parity_with_bootstrapped_foreign_curve(  # noqa: PLR0913
        self,
        calendar: Calendar,
        eur_leg: FixedLeg,
        usd_leg: FixedLeg,
        make_swap,
        eur_curve: YieldTermStructureHandle,
        usd_curve: YieldTermStructureHandle,
    ):
        spot = 1.10
        fx_spot = QuoteHandle(SimpleQuote(spot))

        fx_points = [dict(entry) for entry in FX_FORWARD_POINTS]

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
        usd_handle = swap.discount_curves["USD"]
        conversion = swap._conversion_factor_for("USD")
        manual_pay = _leg_value(replace(usd_leg, rate=usd_par), usd_handle, pay_leg=True)
        manual_rec = _leg_value(replace(eur_leg, rate=eur_par), eur_curve, pay_leg=False)
        expected = manual_rec + manual_pay * conversion
        assert pv == pytest.approx(expected, rel=1e-9)

        spot_date = calendar.advance(Settings.instance().evaluationDate, Period(2, Days), ModifiedFollowing, False)
        df_e_spot = eur_curve.discount(spot_date)
        df_u_spot = usd_handle.discount(spot_date)
        points_map = {str(entry["tenor"]): entry["points"] for entry in fx_points}
        for tenor_label in ("6M", "2Y", "10Y", "30Y", "40Y"):
            far_date = calendar.advance(spot_date, Period(tenor_label), ModifiedFollowing, False)
            df_e = eur_curve.discount(far_date)
            df_u = usd_handle.discount(far_date)
            implied_forward = spot * (df_u / df_e) * (df_e_spot / df_u_spot)
            expected_forward = spot + points_map[tenor_label]
            assert implied_forward == pytest.approx(expected_forward, rel=1e-9)

    def test_pay_receive_symmetry(self, make_swap, eur_leg: FixedLeg, usd_leg: FixedLeg):
        swap_pay_usd = make_swap()
        swap_pay_eur = make_swap(
            paying_leg=eur_leg,
            receiving_leg=usd_leg,
            pricing_currency="EUR",
            collateral_currency="EUR",
        )
        assert swap_pay_usd.npv() == pytest.approx(-swap_pay_eur.npv(), rel=1e-12)

    def test_mark_to_market_alias_matches_npv(self, make_swap):
        swap = make_swap()
        assert swap.mark_to_market() == pytest.approx(swap.npv(), rel=1e-12)


# =======================
# G. Diagnostics & breakdown reporting
# =======================


class TestG_DiagnosticsAndBreakdown:
    def test_breakdown_reports_leg_pvs(self, make_swap):
        swap = make_swap()
        details = swap.npv(breakdown=True)
        assert details["pricing_currency"] == "EUR"
        assert set(details["legs"]) == {"paying", "receiving"}
        assert details["legs"]["paying"]["currency"] == "USD"
        assert details["legs"]["receiving"]["currency"] == "EUR"
        assert details["fx"]["pricing_currency"] == "EUR"
        assert details["fx"]["foreign_currency"] == "USD"
        assert details["fx"]["conversion_factor"] == pytest.approx(swap._spot_conversion_factor)
        assert details["npv"] == pytest.approx(
            details["legs"]["receiving"]["pv_pricing"] + details["legs"]["paying"]["pv_pricing"],
            rel=1e-12,
        )

    def test_breakdown_raises_for_unknown_currency_conversion(self, make_swap):
        swap = make_swap()
        with pytest.raises(ValueError, match="No conversion available"):
            swap._conversion_factor_for("JPY")
