import math
import pytest
from QuantLib import (
    Actual360,
    Date,
    FlatForward,
    SimpleQuote,
    QuoteHandle,
    YieldTermStructureHandle,
    ZeroCurve,
    Period,
    TARGET,
    Settings,
    SavedSettings,
    ModifiedFollowing,
    Days,
)

from pricingengine.instruments.fx_forward import FxForward


# ---------------------------
# Helpers (local to tests)
# ---------------------------


def _points_from_curves(
    *,
    s: float,
    disc_dom: YieldTermStructureHandle,
    disc_for: YieldTermStructureHandle,
    as_of: Date,
    tenors,
    calendar,  # NEW
    convention=ModifiedFollowing,  # NEW
    end_of_month=False,  # NEW
    fixing_days=0,  # NEW: T+0 in this test
):
    """PRICE-side points (F - S) at pillar FAR dates, consistent with helpers."""
    points = []
    # SPOT=ASOF when fixing_days=0; kept for generality
    spot_date = calendar.advance(
        as_of, Period(fixing_days, Days), convention, end_of_month
    )
    for ten in tenors:
        t = ten if isinstance(ten, Period) else Period(str(ten))
        far = calendar.advance(spot_date, t, convention, end_of_month)
        f = s * float(disc_for.discount(far)) / float(disc_dom.discount(far))
        points.append(f - s)
    return points


# ---------------------------
# Fixtures
# ---------------------------


@pytest.fixture
def as_of():
    return Date(5, 5, 2024)


@pytest.fixture
def calendar():
    return TARGET()


@pytest.fixture
def dc():
    return Actual360()


@pytest.fixture
def maturity_9m(as_of):
    return as_of + Period("9M")


@pytest.fixture
def maturity_2y(as_of):
    return as_of + Period("2Y")


@pytest.fixture
def spot_handle():
    # 1.10 PRICE per 1 BASE (e.g., 1.10 USD per EUR)
    return QuoteHandle(SimpleQuote(1.10))


@pytest.fixture
def empty_spot_handle():
    return QuoteHandle()


@pytest.fixture
def flat_domestic(as_of, dc):
    """Flat discount curve (domestic/PRICE ccy) at 2.0%."""
    return YieldTermStructureHandle(FlatForward(as_of, 0.02, dc))


@pytest.fixture
def flat_foreign(as_of, dc):
    """Flat discount curve (foreign/BASE ccy) at 1.0%."""
    return YieldTermStructureHandle(FlatForward(as_of, 0.01, dc))


@pytest.fixture
def finite_domestic(as_of, dc):
    """Finite-horizon domestic curve (ref=asof, max=asof+6M)."""
    d0 = as_of
    d1 = as_of + Period("6M")
    return YieldTermStructureHandle(ZeroCurve((d0, d1), (0.02, 0.02), dc))


@pytest.fixture
def base_ccy():
    return "EUR"


@pytest.fixture
def price_ccy():
    return "USD"


@pytest.fixture
def make_fx(
    as_of, spot_handle, flat_domestic, flat_foreign, base_ccy, price_ccy, dc, calendar
):
    def _make(
        *,
        nominal=100_000_000,
        forward_price=1.11,
        maturity=None,
        base_currency=base_ccy,
        price_currency=price_ccy,
        long_base=True,
        spot=spot_handle,
        disc_d=flat_domestic,
        foreign_for_points=flat_foreign,
        custom_points=None,
        tenors_for_points=(Period("1Y"),),
        fixing_days=0,  # T+0 in c1
        day_counter=dc,
    ):
        # Tenors list
        tenors = [
            Period(t) if not isinstance(t, Period) else t for t in tenors_for_points
        ]

        # Build PRICE-side points only if we can actually read spot and curves;
        # otherwise, fall back to a benign placeholder so constructor can run
        # and raise its own validation errors (as tests expect).
        if custom_points is None:
            try:
                s = float(spot.value())  # may raise if handle is empty
                pts = _points_from_curves(
                    s=s,
                    disc_dom=disc_d,
                    disc_for=foreign_for_points,
                    as_of=as_of,
                    tenors=tenors,
                    calendar=calendar,
                    fixing_days=fixing_days,
                    convention=ModifiedFollowing,
                    end_of_month=False,
                )
                fx_pts_curve = [
                    {"tenor": ten, "points": p} for ten, p in zip(tenors, pts)
                ]
            except Exception:
                # Safe fallback: a single near-dated zero-point that won't
                # query beyond finite curves; lets the constructor perform
                # its own validation and raise the expected ValueError.
                fx_pts_curve = [{"tenor": Period("1M"), "points": 0.0}]
        else:
            fx_pts_curve = custom_points

        # If maturity not given and single tenor, align to the helper’s far date
        if maturity is None and len(tenors) == 1:
            spot_date = calendar.advance(
                as_of, Period(fixing_days, Days), ModifiedFollowing, False
            )
            maturity = calendar.advance(spot_date, tenors[0], ModifiedFollowing, False)
        elif maturity is None:
            maturity = as_of + Period("1Y")

        return FxForward(
            nominal=nominal,
            forward_price=forward_price,
            maturity=maturity,
            base_currency=base_currency,
            price_currency=price_currency,
            long_base=long_base,
            spot=spot,
            discount_domestic=disc_d,
            fx_fwd_pts_curve=fx_pts_curve,
            fixing_days=fixing_days,
            day_counter=day_counter,
            calendar=calendar,
            convention=ModifiedFollowing,
            end_of_month=False,
        )

    return _make


# ---------------------------------------
# A. Construction & invariants
# ---------------------------------------


class TestA_Construct:
    def test_a1_positive_fields(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx(nominal=1_000_000, forward_price=1.05)
            assert fwd.nominal == 1_000_000 and fwd.forward_price == 1.05

    @pytest.mark.parametrize("bad_nom", [0.0, -1.0])
    def test_a2_bad_nominal(self, as_of, make_fx, bad_nom):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(ValueError, match="nominal.*positive"):
                make_fx(nominal=bad_nom)

    @pytest.mark.parametrize("bad_k", [0.0, -1.0])
    def test_a3_bad_forward_price(self, as_of, make_fx, bad_k):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(ValueError, match="forward_price.*positive"):
                make_fx(forward_price=bad_k)

    def test_a4_currency_codes(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(ValueError, match="Unknown currency code"):
                make_fx(base_currency="ZZZ")
            with pytest.raises(ValueError, match="Unknown currency code"):
                make_fx(price_currency="ZZZ")
            with pytest.raises(ValueError, match="must differ"):
                make_fx(base_currency="EUR", price_currency="EUR")

    def test_a5_spot_empty(self, as_of, make_fx, empty_spot_handle):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(ValueError, match="spot .* not set or invalid"):
                make_fx(spot=empty_spot_handle)

    def test_a6_points_curve_empty(
        self, as_of, spot_handle, flat_domestic, base_ccy, price_ccy
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(
                ValueError, match="fx_fwd_pts_curve must contain at least one"
            ):
                FxForward(
                    nominal=1_000_000,
                    forward_price=1.10,
                    maturity=as_of + Period("6M"),
                    base_currency=base_ccy,
                    price_currency=price_ccy,
                    long_base=True,
                    spot=spot_handle,
                    discount_domestic=flat_domestic,
                    fx_fwd_pts_curve=[],  # empty -> error
                )

    def test_a7_curve_out_of_range_no_extrap_domestic_only(
        self, as_of, make_fx, finite_domestic, maturity_9m
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            # domestic curve stops at 6M; class should reject 9M
            with pytest.raises(
                ValueError, match="discount_domestic .* extrapolation disabled"
            ):
                make_fx(disc_d=finite_domestic, maturity=maturity_9m)


# ---------------------------------------
# B. Timeline semantics
# ---------------------------------------


class TestB_Timeline:
    def test_b1_valuation_date_mirrors_settings(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx()
            assert fwd.valuation_date == as_of
            Settings.instance().evaluationDate = as_of + Period("1D")
            assert fwd.valuation_date == as_of + Period("1D")

    @pytest.mark.parametrize(
        "dt, expected",
        [
            ("-1D", False),  # before maturity
            ("0D", False),  # on maturity (not expired)
            ("+1D", True),  # after maturity
        ],
    )
    def test_b2_is_expired_logic(self, as_of, make_fx, dt, expected):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            maturity = as_of
            fwd = make_fx(maturity=maturity)
            Settings.instance().evaluationDate = as_of + Period(dt)
            assert fwd.is_expired == expected


# ---------------------------------------
# C. Fair forward (no-arbitrage)
# ---------------------------------------


class TestC_FairForward:
    def test_c1_flat_parity(
        self, as_of, make_fx, spot_handle, flat_domestic, flat_foreign, dc
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            # Build points from the two flat curves so the bootstrap is consistent
            fwd = make_fx(
                disc_d=flat_domestic,
                foreign_for_points=flat_foreign,
                tenors_for_points=(Period("1Y"),),
                fixing_days=0,
                day_counter=dc,
            )
            s = float(spot_handle.value())
            d_fd = float(flat_domestic.discount(fwd.maturity))
            d_ff = float(flat_foreign.discount(fwd.maturity))
            assert (
                pytest.approx(fwd.fair_forward(), rel=1e-12, abs=1e-12)
                == s * d_ff / d_fd
            )

    def test_c2_equal_curves_imply_f_equals_s(self, as_of, dc, spot_handle):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            s = float(spot_handle.value())
            h = YieldTermStructureHandle(FlatForward(as_of, 0.015, dc))
            # points zero -> DFf == DFd in effect
            fx_pts_curve = [{"tenor": Period("1Y"), "points": 0.0}]
            fwd = FxForward(
                nominal=10_000_000,
                forward_price=s,
                maturity=as_of + Period("1Y"),
                base_currency="EUR",
                price_currency="USD",
                long_base=True,
                spot=spot_handle,
                discount_domestic=h,
                fx_fwd_pts_curve=fx_pts_curve,
            )
            assert pytest.approx(fwd.fair_forward(), rel=1e-12, abs=1e-12) == s


# ---------------------------------------
# D. NPV symmetry & signs
# ---------------------------------------


class TestD_NPV:
    def test_d1_par_forward_zero_pv(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx()
            k_par = fwd.fair_forward()
            fwd_par = fwd.with_forward(k_par)
            assert pytest.approx(fwd_par.npv(), abs=1e-10) == 0.0

    @pytest.mark.parametrize("long_base, sign", [(True, +1.0), (False, -1.0)])
    def test_d2_in_the_money_sign(self, as_of, make_fx, long_base, sign):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx(long_base=long_base)
            f = fwd.fair_forward()
            deep_itm = f - 0.05
            pv = fwd.with_forward(deep_itm).npv()
            assert math.copysign(1.0, pv) == sign

    def test_d3_breakdown_keys_and_values(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx()
            out = fwd.npv(breakdown=True)
            for k in (
                "npv",
                "discount_factor",
                "market_forward",
                "strike",
                "notional",
                "base_currency",
                "price_currency",
            ):
                assert k in out
            d_fd = float(fwd.discount_domestic.discount(fwd.maturity))
            fm = fwd.fair_forward()
            expected = fwd.nominal * d_fd * (fm - fwd.forward_price)
            assert pytest.approx(out["npv"], rel=1e-12, abs=1e-10) == expected

    def test_d4_expired_returns_zero(self, as_of, make_fx):
        with SavedSettings():
            maturity = as_of + Period("3M")
            Settings.instance().evaluationDate = maturity + Period("1D")
            fwd = make_fx(maturity=maturity)
            assert fwd.is_expired is True
            assert fwd.npv() == 0.0
            out = fwd.npv(breakdown=True)
            assert out["npv"] == 0.0 and out["market_forward"] is None


# ---------------------------------------
# E. Handle & curve coverage semantics
# ---------------------------------------


class TestE_HandlesCoverage:
    def test_e1_out_of_range_domestic_only(self, as_of, finite_domestic, spot_handle):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            maturity = as_of + Period("9M")  # beyond finite (6M)
            fx_pts_curve = [
                {"tenor": Period("6M"), "points": 0.0}
            ]  # any points; foreign curve extrapolates internally
            with pytest.raises(
                ValueError, match="discount_domestic .* extrapolation disabled"
            ):
                FxForward(
                    nominal=1_000_000,
                    forward_price=1.1,
                    maturity=maturity,
                    base_currency="EUR",
                    price_currency="USD",
                    long_base=True,
                    spot=spot_handle,
                    discount_domestic=finite_domestic,
                    fx_fwd_pts_curve=fx_pts_curve,
                )

    def test_e2_helpers_required(self, as_of, spot_handle, flat_domestic):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(
                ValueError, match="fx_fwd_pts_curve must contain at least one"
            ):
                FxForward(
                    nominal=1_000_000,
                    forward_price=1.1,
                    maturity=as_of + Period("6M"),
                    base_currency="EUR",
                    price_currency="USD",
                    long_base=True,
                    spot=spot_handle,
                    discount_domestic=flat_domestic,
                    fx_fwd_pts_curve=[],
                )

    def test_e3_single_helper_is_ok_and_extrapolates(
        self, as_of, spot_handle, flat_domestic
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            # Provide only a 6M point, then price a 2Y maturity.
            fx_pts_curve = [{"tenor": Period("6M"), "points": 0.0}]
            fwd = FxForward(
                nominal=1_000_000,
                forward_price=1.1,
                maturity=as_of + Period("2Y"),
                base_currency="EUR",
                price_currency="USD",
                long_base=True,
                spot=spot_handle,
                discount_domestic=flat_domestic,
                fx_fwd_pts_curve=fx_pts_curve,
            )
            assert isinstance(fwd, FxForward)


# ---------------------------------------
# F. Immutability & kw-only API
# ---------------------------------------


class TestF_DataclassTraits:
    def test_f1_frozen(self, as_of, make_fx):
        import dataclasses
        from dataclasses import FrozenInstanceError

        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx()
            assert dataclasses.is_dataclass(fwd)
            assert type(fwd).__dataclass_params__.frozen is True
            with pytest.raises(FrozenInstanceError):
                fwd.forward_price = 9.99

    def test_f2_kw_only(self, as_of, spot_handle, flat_domestic):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            with pytest.raises(TypeError):
                FxForward(  # type: ignore[misc]
                    100_000,
                    1.1,
                    as_of + Period("1Y"),
                    "EUR",
                    "USD",
                    True,
                    spot_handle,
                    flat_domestic,
                    [{"tenor": Period("1Y"), "points": 0.0}],
                )


# ---------------------------------------
# G. Convenience helpers
# ---------------------------------------


class TestG_Convenience:
    def test_g1_with_forward(self, as_of, make_fx):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx(forward_price=1.05)
            fwd2 = fwd.with_forward(1.07)
            assert fwd is not fwd2 and fwd2.forward_price == 1.07

    @pytest.mark.parametrize("bad", [0.0, -0.1])
    def test_g2_with_forward_guards(self, as_of, make_fx, bad):
        with SavedSettings():
            Settings.instance().evaluationDate = as_of
            fwd = make_fx()
            with pytest.raises(ValueError, match="forward_price.*positive"):
                fwd.with_forward(bad)
