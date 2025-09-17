from dataclasses import FrozenInstanceError

import pytest
from QuantLib import (
    TARGET,
    Actual360,
    Annual,
    Calendar,
    Continuous,
    Date,
    DateGeneration,
    DiscountingSwapEngine,
    ForwardCurve,
    IborIndex,
    ModifiedFollowing,
    Period,
    Preceding,
    QuoteHandle,
    SavedSettings,
    Schedule,
    Settings,
    SimpleQuote,
    Swap,
    YieldTermStructureHandle,
    ZeroCurve,
    ZeroSpreadedTermStructure,
)

from pricingengine.cashflows.swap_leg import (
    AmortizedFixedLeg,
    AmortizedFloatingLeg,
    FixedLeg,
    FloatingLeg,
)
from pricingengine.currencies import CURRENCIES
from pricingengine.instruments.interest_rate_swap import InterestRateSwap

# -----------------------
# Shared fixtures
# -----------------------


@pytest.fixture
def issue_date() -> Date:
    return Date(15, 1, 2024)


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
def calendar() -> Calendar:
    return TARGET()


@pytest.fixture
def day_counter():
    return Actual360()


@pytest.fixture
def discount_yts(issue_date, maturity, tenor, calendar, day_counter):
    """
    Flat discount curve as a YieldTermStructureHandle.
    Anchored at issue_date, horizon = last schedule date + tenor.
    """
    flat_zero = 0.025
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
    curve = ZeroCurve((issue_date, horizon), (flat_zero, flat_zero), day_counter)
    return YieldTermStructureHandle(curve)


@pytest.fixture
def index(calendar, day_counter, issue_date, maturity, tenor, currency):
    """
    Flat IborIndex at 2.5%, built from issue_date to (last schedule date + tenor).
    """
    flat_rate = 0.025
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
    # Backfill fixings for determinism
    idx.addFixings(
        tuple(idx.fixingDate(d) for d in sched.dates()),
        tuple(flat_rate for _ in sched.dates()),
        True,
    )
    return idx


@pytest.fixture
def floating_leg(calendar, currency, day_counter, issue_date, nominal, maturity, index, tenor):
    """
    Factory returning a FloatingLeg with given gearing & spread (valuation date is global Settings).
    """

    def make(gearing: float, spread: float) -> FloatingLeg:
        return FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            index=index,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            gearing=gearing,
            spread=spread,
        )

    return make


@pytest.fixture
def fixed_leg(calendar, currency, day_counter, issue_date, nominal, maturity, tenor):
    """
    Factory returning a FixedLeg at a given coupon rate (valuation date is global Settings).
    """

    def make(rate: float) -> FixedLeg:
        return FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=rate,
        )

    return make


# =======================
# A. Construction & invariants
# =======================


class TestA_ConstructionAndInvariants:
    def test_kw_only_positionals_rejected(self, fixed_leg, floating_leg, discount_yts):
        leg1, leg2 = fixed_leg(0.025), floating_leg(1, 0.00)
        with pytest.raises(TypeError):
            _ = InterestRateSwap(leg1, leg2, discount_curve=discount_yts)  # no kw-only

    def test_immutability(self, fixed_leg, floating_leg, discount_yts):
        leg1, leg2 = fixed_leg(0.025), floating_leg(1, 0.00)
        swap = InterestRateSwap(receiving_leg=leg1, paying_leg=leg2, discount_curve=discount_yts)
        with pytest.raises(FrozenInstanceError):
            swap.paying_leg = leg2  # any reassignment should fail

    def test_same_issue_date_required(self, fixed_leg, floating_leg, discount_yts):
        leg1, leg2 = fixed_leg(0.025), floating_leg(1, 0.00)
        object.__setattr__(leg1, "issue_date", leg1.calendar.advance(leg1.issue_date, Period("-1Y")))
        with pytest.raises(ValueError):
            _ = InterestRateSwap(receiving_leg=leg1, paying_leg=leg2, discount_curve=discount_yts)

    def test_same_maturity_required(self, fixed_leg, floating_leg, discount_yts):
        leg1, leg2 = fixed_leg(0.025), floating_leg(1, 0.00)
        object.__setattr__(leg1, "maturity", leg1.calendar.advance(leg1.maturity, Period("-1Y")))
        with pytest.raises(ValueError):
            _ = InterestRateSwap(receiving_leg=leg1, paying_leg=leg2, discount_curve=discount_yts)

    def test_same_currency_required(self, fixed_leg, floating_leg, discount_yts):
        leg1, leg2 = fixed_leg(0.025), floating_leg(1, 0.00)
        object.__setattr__(leg1, "currency", "USD")
        with pytest.raises(ValueError):
            _ = InterestRateSwap(receiving_leg=leg1, paying_leg=leg2, discount_curve=discount_yts)

    def test_fixed_fixed_not_allowed(self, fixed_leg, discount_yts):
        l1, l2 = fixed_leg(0.050), fixed_leg(0.025)
        with pytest.raises(ValueError):
            _ = InterestRateSwap(receiving_leg=l1, paying_leg=l2, discount_curve=discount_yts)

    def test_float_float_not_allowed(self, floating_leg, discount_yts):
        l1, l2 = floating_leg(1, 0.00), floating_leg(2, 0.01)
        with pytest.raises(ValueError):
            _ = InterestRateSwap(receiving_leg=l1, paying_leg=l2, discount_curve=discount_yts)


# =======================
# B. Leg finders & basic properties
# =======================


class TestB_LegFindersAndProperties:
    def test_fixed_leg_property(self, fixed_leg, floating_leg, discount_yts):
        leg_fix, leg_flt = fixed_leg(0.025), floating_leg(1, 0.00)
        swap = InterestRateSwap(receiving_leg=leg_fix, paying_leg=leg_flt, discount_curve=discount_yts)
        assert swap.fixed_leg is leg_fix

    def test_floating_leg_property(self, fixed_leg, floating_leg, discount_yts, index):
        leg_fix, leg_flt = fixed_leg(0.025), floating_leg(1, 0.00)
        # Replace floating leg with amortized to ensure finder still works
        leg_flt_amort = AmortizedFloatingLeg(
            nominal=leg_flt.nominal,
            currency=leg_flt.currency,
            issue_date=leg_flt.issue_date,
            maturity=leg_flt.maturity,
            tenor=leg_flt.tenor,
            index=index,
            calendar=leg_flt.calendar,
            day_counter=leg_flt.day_counter,
            gearing=leg_flt.gearing,
            spread=leg_flt.spread,
            amortization_amount=leg_flt.nominal * 0.05,
            amortization_period=leg_flt.tenor,
            amortization_first_date=leg_flt.issue_date,
            amortization_last_date=leg_flt.maturity,
        )
        swap = InterestRateSwap(receiving_leg=leg_fix, paying_leg=leg_flt_amort, discount_curve=discount_yts)
        assert swap.floating_leg is leg_flt_amort

    def test_properties_forwarded(self, fixed_leg, floating_leg, discount_yts):
        leg_fix, leg_flt = fixed_leg(0.025), floating_leg(1, 0.00)
        swap = InterestRateSwap(receiving_leg=leg_fix, paying_leg=leg_flt, discount_curve=discount_yts)
        assert swap.currency == leg_fix.currency
        assert swap.issue_date == leg_fix.issue_date
        assert swap.maturity == leg_fix.maturity

    def test_valuation_date_tracks_settings(self, fixed_leg, floating_leg, discount_yts, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity - 7
            swap = InterestRateSwap(
                receiving_leg=fixed_leg(0.025),
                paying_leg=floating_leg(1, 0.00),
                discount_curve=discount_yts,
            )
            assert swap.valuation_date == Settings.instance().evaluationDate


# =======================
# C. Expiry / lifecycle
# =======================


class TestC_ExpiryLifecycle:
    def test_not_expired_before_maturity(self, fixed_leg, floating_leg, discount_yts, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity - 1
            swap = InterestRateSwap(
                receiving_leg=fixed_leg(0.025),
                paying_leg=floating_leg(1, 0.00),
                discount_curve=discount_yts,
            )
            assert not swap.is_expired

    def test_not_expired_on_maturity(self, fixed_leg, floating_leg, discount_yts, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity
            swap = InterestRateSwap(
                receiving_leg=fixed_leg(0.025),
                paying_leg=floating_leg(1, 0.00),
                discount_curve=discount_yts,
            )
            assert not swap.is_expired

    def test_expired_after_maturity(self, fixed_leg, floating_leg, discount_yts, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity + 1
            swap = InterestRateSwap(
                receiving_leg=fixed_leg(0.025),
                paying_leg=floating_leg(1, 0.00),
                discount_curve=discount_yts,
            )
            assert swap.is_expired


# =======================
# D. Mark-to-market
# =======================


class TestD_MarkToMarket:
    def test_mtm_antisymmetry_and_near_par(self, fixed_leg, floating_leg, discount_yts):
        """
        With flat discount/forward at same rate and matching fixed coupon,
        the swap should be near par; paying vs receiving flips sign.
        """
        with SavedSettings():
            Settings.instance().evaluationDate = Date(5, 5, 2024)
            leg_flt = floating_leg(1, 0.00)
            leg_fix = fixed_leg(0.025)

            pv1 = InterestRateSwap(
                receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts
            ).mark_to_market()
            pv2 = InterestRateSwap(
                receiving_leg=leg_fix, paying_leg=leg_flt, discount_curve=discount_yts
            ).mark_to_market()
            assert -pv1 == pv2
            assert abs(pv1) / leg_flt.nominal < 1e-3  # ~1bp of notional tolerance

    def test_mtm_zero_when_expired(self, fixed_leg, floating_leg, discount_yts, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity
            leg_flt = floating_leg(1, 0.00)
            leg_fix = fixed_leg(0.025)
            pv = InterestRateSwap(
                receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts
            ).mark_to_market()
            assert pv == 0.0


# =======================
# E. PV01/DV01 and Vanilla equivalence
# =======================


class TestE_VanillaEquivalence:
    def test_vanilla_swap_metrics_match(self, fixed_leg, floating_leg, discount_yts):
        """
        _vanilla_swap_ql should match NPV and leg BPS used by the IRS wrapper.
        """
        with SavedSettings():
            Settings.instance().evaluationDate = Date(5, 5, 2024)

            leg_flt = floating_leg(1, 0.00)
            leg_fix = fixed_leg(0.025)
            swap = InterestRateSwap(receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts)

            npv = swap.mark_to_market()
            pv01 = swap.pv01()
            dv01 = swap.dv01()

            vs = swap._vanilla_swap_ql()
            assert npv == vs.NPV()
            assert pv01 == vs.fixedLegBPS()
            assert dv01 == vs.floatingLegBPS()


# =======================
# F. Curve Greeks: IR01 (discount & forecast)
# =======================


class TestF_CurveGreeks:
    def test_ir01_discount_finite_diff(self, fixed_leg, floating_leg, discount_yts):
        with SavedSettings():
            Settings.instance().evaluationDate = Date(5, 5, 2024)
            leg_flt, leg_fix = floating_leg(1, 0.00), fixed_leg(0.025)
            swap = InterestRateSwap(receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts)

            base = swap.mark_to_market()

            # Build a 1bp bumped discount engine manually
            spread = QuoteHandle(SimpleQuote(1.0 / 10_000.0))
            bumped_ts = ZeroSpreadedTermStructure(discount_yts, spread, Continuous, Annual, discount_yts.dayCounter())
            bumped_engine = DiscountingSwapEngine(YieldTermStructureHandle(bumped_ts))

            pay, rec = swap.paying_leg.cashflows, swap.receiving_leg.cashflows
            sw_bumped = Swap(pay, rec)
            sw_bumped.setPricingEngine(bumped_engine)
            bumped = sw_bumped.NPV()

            fd = (bumped - base) / 1.0
            assert pytest.approx(fd, rel=1e-10, abs=1e-12) == swap.ir01_discount(1.0)

    def test_ir01_forecast_finite_diff(self, fixed_leg, floating_leg, discount_yts):
        with SavedSettings():
            Settings.instance().evaluationDate = Date(5, 5, 2024)
            leg_flt, leg_fix = floating_leg(1, 0.00), fixed_leg(0.025)
            swap = InterestRateSwap(receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts)

            base = swap.mark_to_market()

            # Bump the index's forwarding TS and rebuild the floating leg
            idx0 = swap.floating_leg.index
            fwd = idx0.forwardingTermStructure()
            spread = QuoteHandle(SimpleQuote(1.0 / 10_000.0))
            bumped_fwd_ts = ZeroSpreadedTermStructure(fwd, spread, Continuous, Annual, fwd.dayCounter())
            idx_bumped = idx0.clone(YieldTermStructureHandle(bumped_fwd_ts))

            fl_bumped = swap.floating_leg.with_index(idx_bumped)
            # Re-assemble swap with bumped floating leg
            if swap.floating_leg is swap.paying_leg:
                pay_b, rec_b = fl_bumped.cashflows, swap.receiving_leg.cashflows
            else:
                pay_b, rec_b = swap.paying_leg.cashflows, fl_bumped.cashflows

            sw_bumped = Swap(pay_b, rec_b)
            sw_bumped.setPricingEngine(swap.discount_engine)
            bumped = sw_bumped.NPV()

            fd = (bumped - base) / 1.0
            assert pytest.approx(fd, rel=1e-10, abs=1e-12) == swap.ir01_forecast(1.0)


# =======================
# G. Diagnostics
# =======================


class TestG_Diagnostics:
    def test_cashflow_table_shape_and_pv(self, fixed_leg, floating_leg, discount_yts):
        with SavedSettings():
            Settings.instance().evaluationDate = Date(5, 5, 2024)
            leg_flt, leg_fix = floating_leg(1, 0.00), fixed_leg(0.025)
            swap = InterestRateSwap(receiving_leg=leg_flt, paying_leg=leg_fix, discount_curve=discount_yts)

            df = swap.cashflow_table()
            # rows = number of coupon dates (schedule length - 1)
            expected_rows = len(leg_fix.future_schedule.dates()) - 1
            assert len(df) == expected_rows

            # Required columns exist
            pay_col = f"Pay ({swap.paying_leg.__class__.__name__})"
            rec_col = f"Receive ({swap.receiving_leg.__class__.__name__})"
            for col in [pay_col, rec_col, "Net", "DiscountFactor", "PresentValue"]:
                assert col in df.columns

            # PV in table equals swap NPV (within tight tolerance)
            pv_sum = df["PresentValue"].astype(float).sum()
            assert pytest.approx(pv_sum, rel=1e-12, abs=1e-10) == swap.mark_to_market()


# =======================
# H. Helper behavior mirroring (optional sanity)
# =======================


class TestH_HelperFinders:
    def test_find_fixed_on_amortized_fixed(self, fixed_leg, floating_leg, discount_yts):
        leg_fix = fixed_leg(0.025)
        leg_flt = floating_leg(1, 0.00)
        leg_fix_amort = AmortizedFixedLeg(
            nominal=leg_fix.nominal,
            currency=leg_fix.currency,
            issue_date=leg_fix.issue_date,
            maturity=leg_fix.maturity,
            tenor=leg_fix.tenor,
            calendar=leg_fix.calendar,
            day_counter=leg_fix.day_counter,
            rate=leg_fix.rate,
            amortization_amount=leg_fix.nominal * 0.05,
            amortization_period=leg_fix.tenor,
            amortization_first_date=leg_fix.issue_date,
            amortization_last_date=leg_fix.maturity,
        )
        swap = InterestRateSwap(receiving_leg=leg_fix_amort, paying_leg=leg_flt, discount_curve=discount_yts)
        assert swap.fixed_leg is leg_fix_amort

    def test_find_floating_on_amortized_floating(self, fixed_leg, floating_leg, discount_yts, index):
        leg_fix = fixed_leg(0.025)
        leg_flt = floating_leg(1, 0.00)
        leg_flt_amort = AmortizedFloatingLeg(
            nominal=leg_flt.nominal,
            currency=leg_flt.currency,
            issue_date=leg_flt.issue_date,
            maturity=leg_flt.maturity,
            tenor=leg_flt.tenor,
            index=index,
            calendar=leg_flt.calendar,
            day_counter=leg_flt.day_counter,
            gearing=leg_flt.gearing,
            spread=leg_flt.spread,
            amortization_amount=leg_flt.nominal * 0.05,
            amortization_period=leg_flt.tenor,
            amortization_first_date=leg_flt.issue_date,
            amortization_last_date=leg_flt.maturity,
        )
        swap = InterestRateSwap(receiving_leg=leg_fix, paying_leg=leg_flt_amort, discount_curve=discount_yts)
        assert swap.floating_leg is leg_flt_amort
