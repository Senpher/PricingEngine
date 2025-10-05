# tests/instruments/test_equity_option.py
import dataclasses
from copy import copy

import math
import pytest
from QuantLib import (
    Actual365Fixed,
    Annual,
    BlackConstantVol,
    BlackScholesMertonProcess,
    BlackVolTermStructureHandle,
    Date,
    Exercise,
    FlatForward,
    Option,
    Payoff,
    Period,
    PricingEngine,
    QuoteHandle,
    SavedSettings,
    Settings,
    Simple,
    SimpleQuote,
    UnitedStates,
    VanillaOption as QLVanillaOption,
    YieldTermStructureHandle,
)

from pricingengine.instruments._option import (
    OptionEngineParameters,  # <-- correct import
)
from pricingengine.instruments.equity_option import (
    AmericanVanillaOption,
    BermudanVanillaOption,
    EuropeanDigitalOption,
    EuropeanVanillaOption,
)


# ---------------------------------------------------------------------------
# Global QL eval date pinning (critical for Bermudan fixtures)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_eval_date(valuation_date):
    with SavedSettings():
        Settings.instance().evaluationDate = valuation_date
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calendar():
    return UnitedStates(0)


@pytest.fixture
def day_counter():
    return Actual365Fixed()


@pytest.fixture
def valuation_date():
    return Date(8, 10, 2024)


@pytest.fixture
def currency():
    return "USD"


@pytest.fixture
def strike():
    return 10.0


@pytest.fixture
def underlying_price():
    return 7.85


@pytest.fixture
def dividend():
    return 0.00


@pytest.fixture
def risk_free():
    return 0.0375


@pytest.fixture
def vol():
    return 0.235


@pytest.fixture
def maturity(calendar, valuation_date):
    return calendar.advance(valuation_date, Period("1Y"))


@pytest.fixture
def spot(underlying_price):
    return QuoteHandle(SimpleQuote(underlying_price))


@pytest.fixture
def dividend_curve(valuation_date, day_counter, dividend):
    return YieldTermStructureHandle(
        FlatForward(
            valuation_date,
            QuoteHandle(SimpleQuote(dividend)),
            day_counter,
            Simple,
            Annual,
        )
    )


@pytest.fixture
def risk_free_curve(valuation_date, day_counter, risk_free):
    return YieldTermStructureHandle(
        FlatForward(
            valuation_date,
            QuoteHandle(SimpleQuote(risk_free)),
            day_counter,
            Simple,
            Annual,
        )
    )


@pytest.fixture
def vol_curve(calendar, valuation_date, day_counter, vol):
    return BlackVolTermStructureHandle(
        BlackConstantVol(valuation_date, calendar, vol, day_counter)
    )


@pytest.fixture
def bsm_proc(
    calendar, day_counter, valuation_date, underlying_price, dividend, risk_free, vol
):
    s = QuoteHandle(SimpleQuote(underlying_price))
    d = YieldTermStructureHandle(
        FlatForward(
            valuation_date,
            QuoteHandle(SimpleQuote(dividend)),
            day_counter,
            Simple,
            Annual,
        )
    )
    r = YieldTermStructureHandle(
        FlatForward(
            valuation_date,
            QuoteHandle(SimpleQuote(risk_free)),
            day_counter,
            Simple,
            Annual,
        )
    )
    sigma = BlackVolTermStructureHandle(
        BlackConstantVol(valuation_date, calendar, vol, day_counter)
    )
    return BlackScholesMertonProcess(s, d, r, sigma)


# Option fixtures (default engines per product)
@pytest.fixture
def euro_call(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return EuropeanVanillaOption(
        quantity=25,
        option_type=Option.Call,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
        # default analytic
    )


@pytest.fixture
def euro_put(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return EuropeanVanillaOption(
        quantity=1,
        option_type=Option.Put,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
    )


@pytest.fixture
def amer_call(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return AmericanVanillaOption(
        quantity=25,
        option_type=Option.Call,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
        # default BAW
    )


@pytest.fixture
def amer_put(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return AmericanVanillaOption(
        quantity=1,
        option_type=Option.Put,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
    )


@pytest.fixture
def berm_call(
    calendar,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    ex = (
        calendar.advance(valuation_date, Period("6M")),
        calendar.advance(valuation_date, Period("12M")),
    )
    return BermudanVanillaOption(
        quantity=1,
        option_type=Option.Call,
        strike=strike,
        exercise_dates=ex,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
        # default tree(lr)
    )


@pytest.fixture
def berm_put(
    calendar,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    ex = (
        calendar.advance(valuation_date, Period("6M")),
        calendar.advance(valuation_date, Period("12M")),
    )
    return BermudanVanillaOption(
        quantity=1,
        option_type=Option.Put,
        strike=strike,
        exercise_dates=ex,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
    )


@pytest.fixture
def euro_digital_call(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return EuropeanDigitalOption(
        quantity=1,
        option_type=Option.Call,
        cash_payoff=1.0,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
    )


@pytest.fixture
def euro_digital_put(
    maturity,
    strike,
    valuation_date,
    spot,
    dividend_curve,
    risk_free_curve,
    vol_curve,
):
    return EuropeanDigitalOption(
        quantity=1,
        option_type=Option.Put,
        cash_payoff=1.0,
        strike=strike,
        maturity=maturity,
        spot=spot,
        dividend_curve=dividend_curve,
        risk_free_curve=risk_free_curve,
        vol=vol_curve,
    )


# ---------------------------------------------------------------------------
# A. Construction & validation
# ---------------------------------------------------------------------------


class TestA_Construct:
    def test_a1_quantity_rules(
        self,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with pytest.raises(ValueError):
            EuropeanVanillaOption(
                quantity=0,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
        with pytest.raises(ValueError):
            EuropeanVanillaOption(
                quantity=1.5,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
        opt = EuropeanVanillaOption(
            quantity=-2,
            option_type=Option.Call,
            strike=strike,
            maturity=maturity,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        assert opt.quantity == -2

    def test_a2_option_type_validation(
        self,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with pytest.raises(ValueError):
            EuropeanVanillaOption(
                quantity=1,
                option_type=42,
                strike=strike,
                maturity=maturity,
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )

    def test_a4_subclass_specific_fields(
        self,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with pytest.raises(ValueError):
            EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=0.0,
                maturity=maturity,
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
        with pytest.raises(ValueError):
            EuropeanDigitalOption(
                quantity=1,
                option_type=Option.Call,
                cash_payoff=0.0,
                strike=strike,
                maturity=maturity,
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )

    def test_a5_bermudan_dates_validation(
        self,
        calendar,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with SavedSettings():
            with pytest.raises(ValueError):
                BermudanVanillaOption(
                    quantity=1,
                    option_type=Option.Call,
                    strike=10.0,
                    exercise_dates=(),
                    spot=spot,
                    dividend_curve=dividend_curve,
                    risk_free_curve=risk_free_curve,
                    vol=vol_curve,
                )

            d1 = calendar.advance(valuation_date, Period("6M"))
            d2 = calendar.advance(valuation_date, Period("12M"))

            opt = BermudanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=10.0,
                exercise_dates=(d2, d1, d1),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
            assert opt.exercise_dates == (d1, d2)

    @pytest.mark.parametrize(
        "missing", ["spot", "dividend_curve", "risk_free_curve", "vol"]
    )
    def test_a6_missing_market_inputs(
        self,
        missing,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        kwargs = dict(
            quantity=1,
            option_type=Option.Call,
            strike=strike,
            maturity=maturity,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        kwargs[missing] = None
        with pytest.raises(ValueError) as e:
            EuropeanVanillaOption(**kwargs)
        msg = str(e.value).lower()
        assert "missing market inputs" in msg and missing in msg


# ---------------------------------------------------------------------------
# B. Identity & timeline
# ---------------------------------------------------------------------------


class TestB_TimelineIdentity:
    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_b2_valuation_date_follows_settings(
        self, factory_name, request, valuation_date
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date
            opt = request.getfixturevalue(factory_name)
            assert opt.valuation_date == valuation_date

    def test_b3_is_expired_before_on_after(self, euro_call, maturity):
        with SavedSettings():
            Settings.instance().evaluationDate = maturity - Period("1D")
            assert euro_call.is_expired is False
            Settings.instance().evaluationDate = maturity
            assert euro_call.is_expired is False
            Settings.instance().evaluationDate = maturity + Period("1D")
            assert euro_call.is_expired is True

    def test_b4_is_expired_bermudan_uses_last_date(self, berm_put, valuation_date):
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date
            d1, d2 = berm_put.exercise_dates
            Settings.instance().evaluationDate = d1
            assert berm_put.is_expired is False
            Settings.instance().evaluationDate = d2
            assert berm_put.is_expired is False
            Settings.instance().evaluationDate = d2 + Period("1D")
            assert berm_put.is_expired is True


# ---------------------------------------------------------------------------
# C. Wiring
# ---------------------------------------------------------------------------


class TestC_Wiring:
    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_c1_payoff_is_payoff(self, factory_name, request):
        opt = request.getfixturevalue(factory_name)
        assert issubclass(type(opt._payoff), Payoff)

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_c2_exercise_is_exercise(self, factory_name, request):
        opt = request.getfixturevalue(factory_name)
        assert issubclass(type(opt._exercise), Exercise)

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_c3_engine_is_pricing_engine(self, factory_name, request, bsm_proc):
        opt = request.getfixturevalue(factory_name)
        eng = opt._engine(bsm_proc)
        assert issubclass(type(eng), PricingEngine)

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_c4_ql_option_is_ql_vanilla(self, factory_name, request, bsm_proc):
        opt = request.getfixturevalue(factory_name)
        ql = opt._ql_option()
        assert issubclass(type(ql), QLVanillaOption)


# ---------------------------------------------------------------------------
# D. Pricing basics
# ---------------------------------------------------------------------------


class TestD_Pricing:
    def test_d1_scaling_with_position_size(self, euro_call, bsm_proc):
        with SavedSettings():
            Settings.instance().evaluationDate = euro_call.valuation_date
            single = float(euro_call._ql_option().NPV())
            agg = euro_call.npv()
            assert pytest.approx(agg) == pytest.approx(
                single * euro_call.quantity * euro_call.contract_size
            )

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    def test_d2_expired_returns_zero(self, factory_name, request, bsm_proc):
        opt = copy(request.getfixturevalue(factory_name))
        with SavedSettings():
            if hasattr(opt, "maturity") and not hasattr(opt, "exercise_dates"):
                Settings.instance().evaluationDate = opt.maturity + Period("1M")
            else:
                Settings.instance().evaluationDate = opt.exercise_dates[-1] + Period(
                    "1M"
                )
            assert opt.is_expired is True
            assert opt.npv() == 0.0

    def test_d3_american_vs_european_call_no_dividends(
        self, amer_call, euro_call, bsm_proc
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = euro_call.valuation_date
            pv_e = euro_call.npv()
            pv_a = amer_call.npv()
            assert pytest.approx(pv_a, rel=5e-3, abs=5e-3) == pytest.approx(
                pv_e, rel=5e-3, abs=5e-3
            )

    def test_d4_bermudan_between_euro_and_american(
        self, berm_put, amer_put, euro_put, bsm_proc
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = euro_put.valuation_date
            pv_e = euro_put.npv()
            pv_b = berm_put.npv()
            pv_a = amer_put.npv()
            assert pv_e <= pv_b <= pv_a


# ---------------------------------------------------------------------------
# E. Greeks
# ---------------------------------------------------------------------------


class TestE_Greeks:
    GREEK_FUNCS = ("delta", "gamma", "vega", "rho", "theta")

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    @pytest.mark.parametrize("greek", GREEK_FUNCS)
    def test_e1_greeks_exist_and_finite(self, factory_name, request, greek, bsm_proc):
        opt = request.getfixturevalue(factory_name)
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            try:
                val = getattr(ql, greek)()
            except RuntimeError:
                per_unit_method = getattr(opt, greek)
                val = per_unit_method()
            assert isinstance(val, float)
            assert math.isfinite(val)

    @pytest.mark.parametrize("greek", GREEK_FUNCS)
    def test_e2_european_call_put_signs_and_bounds(
        self, euro_call, euro_put, bsm_proc, greek
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = euro_call.valuation_date
            ql_c = euro_call._ql_option()
            ql_p = euro_put._ql_option()

            vc = getattr(ql_c, greek)()
            vp = getattr(ql_p, greek)()

            if greek == "delta":
                assert 0.0 <= vc <= 1.0
                assert -1.0 <= vp <= 0.0
            elif greek == "gamma":
                assert vc >= 0.0 and vp >= 0.0
            elif greek == "vega":
                assert vc >= 0.0 and vp >= 0.0
            elif greek == "rho":
                assert vc > 0.0 and vp < 0.0
            elif greek == "theta":
                # Call theta should be non-positive; put theta can be of either sign
                assert vc <= 0.0

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    @pytest.mark.parametrize("greek", GREEK_FUNCS)
    def test_e3_expired_greeks_zero(self, factory_name, greek, request, bsm_proc):
        opt = request.getfixturevalue(factory_name)
        with SavedSettings():
            if hasattr(opt, "maturity") and not hasattr(opt, "exercise_dates"):
                Settings.instance().evaluationDate = opt.maturity + Period("1D")
            else:
                Settings.instance().evaluationDate = opt.exercise_dates[-1] + Period(
                    "1D"
                )

            ql = opt._ql_option()
            try:
                val = getattr(ql, greek)()
            except RuntimeError:
                val = getattr(opt, greek)(bsm_proc)

            assert abs(val) < 1e-10

    @pytest.mark.parametrize(
        "factory_name",
        [
            "euro_call",
            "euro_put",
            "amer_call",
            "amer_put",
            "berm_call",
            "berm_put",
            "euro_digital_call",
            "euro_digital_put",
        ],
    )
    @pytest.mark.parametrize("greek", GREEK_FUNCS)
    def test_e4_scaling_behavior(self, factory_name, greek, request, bsm_proc):
        opt = request.getfixturevalue(factory_name)
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            try:
                per_unit = getattr(ql, greek)()
            except RuntimeError:
                per_unit = getattr(opt, greek)()

            qty_scale = opt.quantity * opt.contract_size

            per_unit_method = getattr(opt, greek, None)
            scaled_method = (
                getattr(opt, f"total_{greek}", None)
                or getattr(opt, f"scaled_{greek}", None)
                or getattr(opt, f"{greek}_scaled", None)
            )

            checked_any = False

            if callable(per_unit_method):
                v = per_unit_method()
                assert pytest.approx(v, rel=1e-6, abs=1e-8) == per_unit
                checked_any = True

            if callable(scaled_method):
                try:
                    vt = scaled_method(bsm_proc)
                except TypeError:
                    vt = scaled_method()
                assert pytest.approx(vt, rel=1e-6, abs=1e-8) == per_unit * qty_scale
                checked_any = True

            if not checked_any:
                pytest.xfail(f"{factory_name} has no {greek} method(s) implemented yet")

    # A small digital monotonicity check vs strike
    def test_e6_digital_call_monotone_in_strike(
        self,
        maturity,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        lower = EuropeanDigitalOption(
            quantity=1,
            option_type=Option.Call,
            cash_payoff=1.0,
            strike=9.0,
            maturity=maturity,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        higher = EuropeanDigitalOption(
            quantity=1,
            option_type=Option.Call,
            cash_payoff=1.0,
            strike=11.0,
            maturity=maturity,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date
            assert lower.npv() >= higher.npv()


class TestE_EngineMatrixExhaustive:
    GREEK_FUNCS = ("delta", "gamma", "vega", "rho", "theta")

    # What we *expect* each engine to provide (by QL design/build in most wheels)
    ENGINE_CAPS = {
        "AnalyticEuropeanEngine": {"both": {"delta", "gamma", "vega", "rho", "theta"}},
        "FdBlackScholesVanillaEngine": {
            "both": {"delta", "gamma", "theta"}
        },  # what your wheel exposes
        # BAW varies by build; your probe shows calls OK, puts missing -> reflect that.
        "BaroneAdesiWhaleyApproximationEngine": {
            "call": {"delta", "gamma", "vega", "rho", "theta"},
            "put": set(),  # price-only in your environment
        },
        "BjerksundStenslandApproximationEngine": {
            "both": {"delta", "gamma", "vega", "rho", "theta"}
        },
        # Trees: most wheels expose these three
        "BinomialVanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialJRVanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialCRRVanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialTianVanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialTrigeorgisVanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialJ4VanillaEngine": {"both": {"delta", "gamma", "theta"}},
        "BinomialLRVanillaEngine": {"both": {"delta", "gamma", "theta"}},
    }

    TREE_METHODS = ("jr", "crr", "tian", "trigeorgis", "lr", "joshi")

    # Engine params factories (OptionEngineParameters.* — no .model attribute)
    ENGINE_FACTORIES = {
        "analytic": OptionEngineParameters.analytic,
        "fd": lambda: OptionEngineParameters.fd(nt=121, nx=241),
        "baw": OptionEngineParameters.baw,
        "bjerksund": OptionEngineParameters.bjerksund,
        **{
            f"tree_{m}": (lambda m=m: OptionEngineParameters.tree(steps=201, method=m))
            for m in TREE_METHODS
        },
    }

    # For each option fixture name, which engines are supported vs rejected
    OPTION_ENGINE_MATRIX = {
        # Europeans
        "euro_call": {
            "supported": ("analytic", "fd"),
            "rejected": ("baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
        },
        "euro_put": {
            "supported": ("analytic", "fd"),
            "rejected": ("baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
        },
        "euro_digital_call": {
            "supported": ("analytic", "fd"),
            "rejected": ("baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
        },
        "euro_digital_put": {
            "supported": ("analytic", "fd"),
            "rejected": ("baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
        },
        # Americans: approximations, all trees, FD
        "amer_call": {
            "supported": (
                "baw",
                "bjerksund",
                "fd",
                *[f"tree_{m}" for m in TREE_METHODS],
            ),
            "rejected": ("analytic",),
        },
        "amer_put": {
            "supported": (
                "baw",
                "bjerksund",
                "fd",
                *[f"tree_{m}" for m in TREE_METHODS],
            ),
            "rejected": ("analytic",),
        },
        # Bermudans: all trees + FD
        "berm_call": {
            "supported": ("fd", *[f"tree_{m}" for m in TREE_METHODS]),
            "rejected": ("analytic", "baw", "bjerksund"),
        },
        "berm_put": {
            "supported": ("fd", *[f"tree_{m}" for m in TREE_METHODS]),
            "rejected": ("analytic", "baw", "bjerksund"),
        },
    }

    OPTION_FIXTURE_NAMES = [
        "euro_call",
        "euro_put",
        "euro_digital_call",
        "euro_digital_put",
        "amer_call",
        "amer_put",
        "berm_call",
        "berm_put",
    ]

    @staticmethod
    def _rebuild_with(opt, engine_params):
        K = type(opt)
        base = dict(
            quantity=opt.quantity,
            option_type=opt.option_type,
            engine_params=engine_params,
            spot=opt.spot,
            dividend_curve=opt.dividend_curve,
            risk_free_curve=opt.risk_free_curve,
            vol=opt.vol,
            contract_size=opt.contract_size,
            greek_bump_policy=getattr(opt, "greek_bump_policy", "sticky_strike"),
        )
        if isinstance(opt, EuropeanVanillaOption):
            return K(strike=opt.strike, maturity=opt.maturity, **base)
        if isinstance(opt, EuropeanDigitalOption):
            return K(
                cash_payoff=opt.cash_payoff,
                strike=opt.strike,
                maturity=opt.maturity,
                **base,
            )
        if isinstance(opt, AmericanVanillaOption):
            return K(strike=opt.strike, maturity=opt.maturity, **base)
        if isinstance(opt, BermudanVanillaOption):
            return K(
                strike=opt.strike, exercise_dates=tuple(opt.exercise_dates), **base
            )
        raise TypeError(f"Unknown option subclass: {K!r}")

    @staticmethod
    def _engine_class_name(opt, bsm_proc) -> str:
        # Ask the option which engine it wired in (no process arg)
        eng = opt._engine(bsm_proc)
        raw = type(eng).__name__
        return raw

    @pytest.mark.parametrize("factory_name", list(OPTION_ENGINE_MATRIX.keys()))
    @pytest.mark.parametrize(
        "engine_key",
        ("analytic", "fd", "baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
    )
    def test_engine_support_contract(self, factory_name, engine_key, request):
        opt0 = request.getfixturevalue(factory_name)
        params_factory = self.ENGINE_FACTORIES[engine_key]
        params = params_factory()

        support = self.OPTION_ENGINE_MATRIX[factory_name]
        is_supported = engine_key in support["supported"]

        if not is_supported:
            with pytest.raises(ValueError):
                self._rebuild_with(opt0, params)
        else:
            # should construct cleanly
            _ = self._rebuild_with(opt0, params)

    @pytest.mark.parametrize("greek", GREEK_FUNCS)
    @pytest.mark.parametrize(
        "engine_key",
        ("analytic", "fd", "baw", "bjerksund", *[f"tree_{m}" for m in TREE_METHODS]),
    )
    @pytest.mark.parametrize("factory_name", OPTION_FIXTURE_NAMES)
    def test_engine_caps_vs_wrapper_behavior(
        self, factory_name, engine_key, greek, request, bsm_proc
    ):
        """
        For EVERY (option, engine, greek):
          - If the engine is rejected by the constructor -> assert ValueError (this IS the test).
          - Else:
              * If engine is expected to expose `greek` -> QL greek finite; wrapper finite & ≈ QL
              * If not expected -> QL raises RuntimeError; wrapper FD fallback finite
        """
        opt0 = request.getfixturevalue(factory_name)
        params = self.ENGINE_FACTORIES[engine_key]()

        # 1) Construction either fails (unsupported combo) or succeeds.
        try:
            opt = self._rebuild_with(opt0, params)
        except ValueError:
            # Rejection is the expected behavior for unsupported combos.
            # Since this case can’t reach greeks, this assertion completes this param triple.
            return

        # 2) Constructed -> check caps vs behavior
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            eng_name = self._engine_class_name(opt, bsm_proc)
            caps_entry = self.ENGINE_CAPS.get(eng_name, {})
            side = "call" if opt.option_type == Option.Call else "put"
            expected_caps = caps_entry.get(side, caps_entry.get("both", set()))

            if greek in expected_caps:
                # Engine is supposed to provide it
                q_val = getattr(ql, greek)()
                assert math.isfinite(q_val), f"{eng_name}.{greek} must be finite"
                o_val = getattr(opt, greek)()
                assert math.isfinite(o_val)
                # tighter for analytic, looser for lattice/FD
                if eng_name == "AnalyticEuropeanEngine":
                    assert o_val == pytest.approx(q_val, rel=1e-5, abs=1e-8)
                else:
                    assert o_val == pytest.approx(q_val, rel=5e-3, abs=5e-6)
            else:
                # Engine not expected to provide it -> QL raises, wrapper falls back (FD) and is finite
                with pytest.raises(RuntimeError):
                    getattr(ql, greek)()
                o_val = getattr(opt, greek)()
                assert math.isfinite(o_val), (
                    f"{type(opt).__name__}.{greek} must be finite via FD fallback"
                )


# ---------------------------------------------------------------------------
# F. Dataclass traits (frozen)
# ---------------------------------------------------------------------------


class TestF_Frozen:
    def test_f1_frozen_immutability(self, euro_call):
        import dataclasses

        assert dataclasses.is_dataclass(euro_call)
        assert type(euro_call).__dataclass_params__.frozen is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            euro_call.strike = 9.99


# ---------------------------------------------------------------------------
# G. Engine/grid sanity (FD)
# ---------------------------------------------------------------------------


class TestG_Engines:
    def test_g1_fd_grid_sanity_american_call_matches_euro(
        self,
        maturity,
        strike,
        valuation_date,
        bsm_proc,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date

            eu = EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.analytic(),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
            pv_e = eu.npv()

            am_coarse = AmericanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.fd(nt=25, nx=50),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )
            am_fine = AmericanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.fd(nt=200, nx=400),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )

            pv_c = am_coarse.npv()
            pv_f = am_fine.npv()

            assert pytest.approx(pv_c, rel=2e-2, abs=2e-2) == pytest.approx(
                pv_e, rel=2e-2, abs=2e-2
            )
            assert pytest.approx(pv_f, rel=5e-3, abs=5e-3) == pytest.approx(
                pv_e, rel=5e-3, abs=5e-3
            )
            assert abs(pv_f - pv_c) < 0.5

    def test_g2_bermudan_bounds_stable_across_grids(
        self, berm_put, amer_put, euro_put, bsm_proc
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = euro_put.valuation_date

            pv_b0 = berm_put.npv()

            berm_coarse = BermudanVanillaOption(
                quantity=berm_put.quantity,
                option_type=berm_put.option_type,
                strike=berm_put.strike,
                exercise_dates=berm_put.exercise_dates,
                engine_params=OptionEngineParameters.fd(nt=50, nx=100),
                spot=berm_put.spot,
                dividend_curve=berm_put.dividend_curve,
                risk_free_curve=berm_put.risk_free_curve,
                vol=berm_put.vol,
            )
            pv_b1 = berm_coarse.npv()

            pv_e = euro_put.npv()
            pv_a = amer_put.npv()

            for pv in (pv_b0, pv_b1):
                assert pv_e <= pv <= pv_a

    # FD convergence sanity for European with explicit FD engines
    def test_g3_euro_fd_converges_with_grid(
        self,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date

            eu_ref = EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.analytic(),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            ).npv()

            eu_fd_coarse = EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.fd(nt=25, nx=50),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            ).npv()

            eu_fd_fine = EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.fd(nt=200, nx=400),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            ).npv()

            assert abs(eu_fd_fine - eu_ref) < abs(eu_fd_coarse - eu_ref)
            assert pytest.approx(eu_fd_fine, rel=5e-3, abs=5e-3) == pytest.approx(
                eu_ref, rel=5e-3, abs=5e-3
            )


# ---------------------------------------------------------------------------
# H. Engine coverage and invalid-combo guards
# ---------------------------------------------------------------------------


class TestH_EngineMatrix:
    TREE_METHODS = ("jr", "crr", "tian", "trigeorgis", "lr", "joshi")

    # ------------------ European ------------------

    @pytest.mark.parametrize(
        "factory", [OptionEngineParameters.analytic, OptionEngineParameters.fd]
    )
    def test_h1_euro_supported_engines(
        self,
        factory,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
        bsm_proc,
    ):
        params = factory(
            **({"nt": 60, "nx": 120} if factory is OptionEngineParameters.fd else {})
        )
        opt = EuropeanVanillaOption(
            quantity=1,
            option_type=Option.Call,
            strike=strike,
            maturity=maturity,
            engine_params=params,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            assert math.isfinite(float(ql.NPV()))
            try:
                d = ql.delta()
            except RuntimeError:
                d = opt.delta()
            assert math.isfinite(d)

    @pytest.mark.parametrize(
        "bad_factory",
        [
            OptionEngineParameters.baw,
            OptionEngineParameters.bjerksund,
            OptionEngineParameters.tree,
        ],
    )
    def test_h2_euro_reject_unsupported_engines(
        self,
        bad_factory,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        with pytest.raises(ValueError):
            EuropeanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=bad_factory(
                    **(
                        {"steps": 111, "tree_method": "lr"}
                        if bad_factory is OptionEngineParameters.tree
                        else {}
                    )
                ),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )

    # ------------------ American ------------------

    @pytest.mark.parametrize(
        "factory",
        [
            OptionEngineParameters.baw,
            OptionEngineParameters.bjerksund,
            OptionEngineParameters.fd,
        ],
    )
    def test_h3_amer_supported_non_tree_engines(
        self,
        factory,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
        bsm_proc,
    ):
        params = factory(
            **({"nt": 60, "nx": 120} if factory is OptionEngineParameters.fd else {})
        )
        opt = AmericanVanillaOption(
            quantity=1,
            option_type=Option.Put,
            strike=strike,
            maturity=maturity,
            engine_params=params,
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            assert math.isfinite(float(ql.NPV()))
            try:
                d = ql.delta()
            except RuntimeError:
                d = opt.delta()
            assert math.isfinite(d)

    @pytest.mark.parametrize("tree_method", TREE_METHODS)
    def test_h4_amer_supported_tree_variants(
        self,
        tree_method,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
        bsm_proc,
    ):
        opt = AmericanVanillaOption(
            quantity=1,
            option_type=Option.Call,
            strike=strike,
            maturity=maturity,
            engine_params=OptionEngineParameters.tree(steps=201, method=tree_method),
            spot=spot,
            dividend_curve=dividend_curve,
            risk_free_curve=risk_free_curve,
            vol=vol_curve,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            assert math.isfinite(float(ql.NPV()))
            try:
                d = ql.delta()
            except RuntimeError:
                d = opt.delta()
            assert math.isfinite(d)

    def test_h5_amer_reject_invalid_engine_string(
        self,
        maturity,
        strike,
        valuation_date,
        spot,
        dividend_curve,
        risk_free_curve,
        vol_curve,
    ):
        # The class validates the engine name via the OptionEngineParameters instance,
        # so to simulate a "bad" engine we can bypass via a tiny shim if needed.
        # Here we assert a ValueError is raised when passing a tree with bad method.
        with pytest.raises(ValueError):
            AmericanVanillaOption(
                quantity=1,
                option_type=Option.Call,
                strike=strike,
                maturity=maturity,
                engine_params=OptionEngineParameters.tree(steps=10, method="made-up"),
                spot=spot,
                dividend_curve=dividend_curve,
                risk_free_curve=risk_free_curve,
                vol=vol_curve,
            )

    # ------------------ Bermudan ------------------

    @pytest.mark.parametrize("factory", [OptionEngineParameters.fd])
    def test_h6_berm_supported_fd(
        self,
        factory,
        berm_put,
        bsm_proc,
    ):
        base = berm_put
        opt = BermudanVanillaOption(
            quantity=base.quantity,
            option_type=base.option_type,
            strike=base.strike,
            exercise_dates=base.exercise_dates,
            engine_params=factory(nt=80, nx=160),
            spot=base.spot,
            dividend_curve=base.dividend_curve,
            risk_free_curve=base.risk_free_curve,
            vol=base.vol,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            assert math.isfinite(float(ql.NPV()))
            try:
                d = ql.delta()
            except RuntimeError:
                d = opt.delta()
            assert math.isfinite(d)

    @pytest.mark.parametrize("tree_method", TREE_METHODS)
    def test_h7_berm_supported_tree_variants(
        self,
        tree_method,
        berm_call,
        bsm_proc,
    ):
        base = berm_call
        opt = BermudanVanillaOption(
            quantity=base.quantity,
            option_type=base.option_type,
            strike=base.strike,
            exercise_dates=base.exercise_dates,
            engine_params=OptionEngineParameters.tree(steps=321, method=tree_method),
            spot=base.spot,
            dividend_curve=base.dividend_curve,
            risk_free_curve=base.risk_free_curve,
            vol=base.vol,
        )
        with SavedSettings():
            Settings.instance().evaluationDate = opt.valuation_date
            ql = opt._ql_option()
            assert math.isfinite(float(ql.NPV()))
            try:
                d = ql.delta()
            except RuntimeError:
                d = opt.delta()
            assert math.isfinite(d)

    @pytest.mark.parametrize(
        "bad_factory",
        [
            OptionEngineParameters.analytic,
            OptionEngineParameters.baw,
            OptionEngineParameters.bjerksund,
        ],
    )
    def test_h8_berm_reject_unsupported_engines(
        self,
        bad_factory,
        berm_call,
    ):
        base = berm_call
        with pytest.raises(ValueError):
            BermudanVanillaOption(
                quantity=base.quantity,
                option_type=base.option_type,
                strike=base.strike,
                exercise_dates=base.exercise_dates,
                engine_params=bad_factory(),
                spot=base.spot,
                dividend_curve=base.dividend_curve,
                risk_free_curve=base.risk_free_curve,
                vol=base.vol,
            )


# ---------------------------------------------------------------------------
# I. Cross Engine Stability
# ---------------------------------------------------------------------------


class TestI_CrossEngineStability:
    # engine-key -> OptionEngineParameters factory
    ENGINES = {
        "analytic": lambda: OptionEngineParameters.analytic(),
        "d_analytic": lambda: OptionEngineParameters.analytic(),
        "fd": lambda: OptionEngineParameters.fd(nt=181, nx=361),
        "d_fd": lambda: OptionEngineParameters.fd(nt=400, nx=800),
        "tree_lr": lambda: OptionEngineParameters.tree(steps=801, method="lr"),
        "tree_crr": lambda: OptionEngineParameters.tree(steps=801, method="crr"),
        "baw": lambda: OptionEngineParameters.baw(),
        "bjerksund": lambda: OptionEngineParameters.bjerksund(),
    }

    # symmetric tolerances for price & greek comparisons by (ref,cmp)
    TOLS = {
        ("analytic", "fd"): dict(p_abs=1e-2, g_rel=1e-2, g_abs=1e-2),
        ("d_analytic", "d_fd"): dict(p_abs=0.2, g_rel=0.2, g_abs=0.2),
        ("analytic", "tree_lr"): dict(p_abs=1e-2, g_rel=1e-2, g_abs=1e-2),
        ("fd", "tree_lr"): dict(p_abs=1e-2, g_rel=1e-2, g_abs=1e-2),
        ("baw", "tree_lr"): dict(p_abs=2e-1, g_rel=2e-1, g_abs=2e-1),
        ("baw", "fd"): dict(p_abs=2e-1, g_rel=2e-1, g_abs=2e-1),
        ("tree_lr", "tree_crr"): dict(p_abs=1e-1, g_rel=1e-1, g_abs=1e-1),
        ("tree_lr", "fd"): dict(p_abs=1e-1, g_rel=1e-1, g_abs=1e-1),
    }

    GREEKS = ("delta", "gamma", "vega", "rho", "theta")

    # enumerate pairs you want to check per style
    PAIRS_BY_STYLE = {
        "euro": [("analytic", "fd"), ("analytic", "tree_lr")],
        "amer": [("baw", "tree_lr"), ("baw", "fd"), ("tree_lr", "fd")],
        "berm": [("tree_lr", "tree_crr"), ("tree_lr", "fd")],
        "digital": [("d_analytic", "d_fd")],
    }

    @staticmethod
    def _build(opt, engine_key):
        # always build params by calling the factory
        params_factory = TestI_CrossEngineStability.ENGINES[engine_key]
        params = params_factory()

        common = dict(
            quantity=opt.quantity,
            option_type=opt.option_type,
            engine_params=params,
            spot=opt.spot,
            dividend_curve=opt.dividend_curve,
            risk_free_curve=opt.risk_free_curve,
            vol=opt.vol,
            contract_size=opt.contract_size,
        )

        K = type(opt)
        # European digital
        if hasattr(opt, "maturity") and hasattr(opt, "cash_payoff"):
            return K(
                cash_payoff=opt.cash_payoff,
                strike=opt.strike,
                maturity=opt.maturity,
                **common,
            )

        # European vanilla
        if (
            hasattr(opt, "maturity")
            and hasattr(opt, "strike")
            and not hasattr(opt, "exercise_dates")
        ):
            return K(strike=opt.strike, maturity=opt.maturity, **common)

        # Bermudan vanilla
        if hasattr(opt, "exercise_dates"):
            return K(
                strike=opt.strike, exercise_dates=tuple(opt.exercise_dates), **common
            )

        raise TypeError(f"Unsupported option type for builder: {K!r}")

    @pytest.mark.parametrize(
        "factory_name, style",
        [
            ("euro_call", "euro"),
            ("euro_put", "euro"),
            ("euro_digital_call", "digital"),
            ("euro_digital_put", "digital"),
            ("amer_call", "amer"),
            ("amer_put", "amer"),
            ("berm_call", "berm"),
            ("berm_put", "berm"),
        ],
    )
    def test_price_and_greeks_stability(self, factory_name, style, request):
        base = request.getfixturevalue(factory_name)
        for ref_key, cmp_key in self.PAIRS_BY_STYLE[style]:
            # try build both; skip pair if constructor deliberately rejects
            try:
                ref = self._build(base, ref_key)
                cmp_ = self._build(base, cmp_key)
            except ValueError:
                continue

            # pick tolerances, swapping order if needed
            tols = self.TOLS.get((ref_key, cmp_key)) or self.TOLS.get(
                (cmp_key, ref_key)
            )
            assert tols is not None, f"No tolerances for pair {(ref_key, cmp_key)}"
            with SavedSettings():
                Settings.instance().evaluationDate = ref.valuation_date
                p_ref = ref.npv_per_unit()
                p_cmp = cmp_.npv_per_unit()
            assert p_cmp == pytest.approx(p_ref, abs=tols["p_abs"])

            for g in self.GREEKS:
                gr = getattr(ref, g)()
                gc = getattr(cmp_, g)()
                if abs(gr) < 1e-8:
                    assert gc == pytest.approx(gr, abs=tols["g_abs"])
                else:
                    assert gc == pytest.approx(gr, rel=tols["g_rel"], abs=tols["g_abs"])


# ---------------------------------------------------------------------------
# J. Extra Tests
# ---------------------------------------------------------------------------


def test_digital_cash_payoff_scales_linearly(euro_digital_call):
    base = euro_digital_call
    dbl = dataclasses.replace(base, cash_payoff=2.0 * base.cash_payoff)
    with SavedSettings():
        Settings.instance().evaluationDate = base.valuation_date
        p1 = base.npv_per_unit()
        p2 = dbl.npv_per_unit()
    assert p2 == pytest.approx(2.0 * p1, rel=1e-12, abs=1e-12)
