from dataclasses import FrozenInstanceError
import math

import numpy as np
import pandas as pd
import pytest
from QuantLib import (
    TARGET,
    Actual360,
    Actual365Fixed,
    Annual,
    BachelierSwaptionEngine,
    BlackCalibrationHelper,
    BlackSwaptionEngine,
    Compounded,
    ConstantSwaptionVolatility,
    Date,
    DateGeneration,
    EndCriteria,
    EuropeanExercise,
    FlatForward,
    Following,
    ForwardCurve,
    HullWhite,
    IborIndex,
    JamshidianSwaptionEngine,
    LevenbergMarquardt,
    Matrix,
    ModifiedFollowing,
    Months,
    Normal,
    NullCalendar,
    Period,
    Preceding,
    QuoteHandle,
    RelinkableSwaptionVolatilityStructureHandle,
    SabrSwaptionVolatilityCube,
    SavedSettings,
    Schedule,
    Settings,
    Settlement,
    ShiftedLognormal,
    SimpleQuote,
    SwapIndex,
    SwaptionHelper,
    SwaptionVolatilityCube,
    SwaptionVolatilityMatrix,
    SwaptionVolatilityStructureHandle,
    TimeGrid,
    YieldTermStructureHandle,
    ZeroCurve,
)
from QuantLib import (
    Swaption as QLSwaption,
)

from PricingEngine.Instruments import InterestRateSwap, Swaption
from PricingEngine.Instruments.Common import CURRENCIES, FixedLeg, FloatingLeg


@pytest.fixture
def valuation_date():
    # Save current global settings and restore them after the test
    with SavedSettings():
        d = Date(10, 6, 2025)
        Settings.instance().evaluationDate = d
        yield d  # tests can still depend on 'valuation_date'  # upon exiting the context, SavedSettings restores the previous state


@pytest.fixture
def issue_date():
    return Date(10, 6, 2026)


@pytest.fixture
def maturity():
    return Date(10, 6, 2036)


@pytest.fixture
def tenor():
    return Period("3M")


@pytest.fixture
def nominal():
    return 100_000_000.0


@pytest.fixture
def currency():
    return "SEK"


@pytest.fixture
def calendar():
    return TARGET()


@pytest.fixture
def day_counter():
    return Actual360()


# ---------- DISCOUNT CURVE (dense zeros out to 40y) ----------
@pytest.fixture
def discount_curve_handle(valuation_date, calendar, day_counter):
    """
    Dense, realistic zero curve (OIS-like shape) with >70 nodes out to 40y.
    We use ZeroCurve so discount factors are robust well beyond swaption horizons.
    """
    tenors = (
        [Period("1W"), Period("2W"), Period("3W")]
        + [Period(f"{m}M") for m in range(1, 37)]  # 1M..36M
        + [Period(f"{y}Y") for y in range(4, 41)]  # 4Y..40Y
    )
    dates = [calendar.advance(valuation_date, t, ModifiedFollowing) for t in tenors]
    # Strictly increasing and starting strictly after valuation_date:
    dates = [d for d in dates if d > valuation_date]
    assert len(dates) >= 50

    dc365 = Actual365Fixed()

    def ois_zero(t_years: float) -> float:
        # Smooth, realistic-ish OIS zero curve: ~1.4% front, hump ~2.4% around 7-10y, fades a touch long-end
        return (
            0.014
            + 0.010 * (1.0 - math.exp(-t_years / 2.5))  # rising belly
            + 0.003 * math.exp(-(((t_years - 9.0) / 5.0) ** 2))  # mild hump ~9y
            - 0.001 * math.exp(-(((t_years - 30.0) / 10.0) ** 2))  # slight long-end ease
        )

    zeros = [ois_zero(dc365.yearFraction(valuation_date, d)) for d in dates]

    zc = ZeroCurve(dates, zeros, dc365, calendar)
    zc.enableExtrapolation()
    return YieldTermStructureHandle(zc)


# ---------- INDEX (forwarding curve + past fixings) ----------
@pytest.fixture
def index(
    valuation_date,
    issue_date,
    maturity,
    tenor,
    calendar,
    day_counter,
    currency,
    discount_curve_handle,
):
    """
    Forwarding curve (instantaneous forwards) with basis over an OIS-like shape,
    plus ALL fixings populated (past=constant today's forward future=projected).
    Crucial fix: include 0D/1D/2D pillars so the curve reference date <= any query date.
    """

    dc365 = Actual365Fixed()

    # --- Build dense forward-curve pillars ---
    # Add 0D/1D/2D to avoid "negative time" when discounting spot starts (T+2).
    early = [Period("1D"), Period("2D")]
    core = (
        [Period("1W"), Period("2W"), Period("3W")]
        + [Period(f"{m}M") for m in range(1, 37)]
        + [Period(f"{y}Y") for y in range(4, 41)]
    )

    fwd_dates = [valuation_date] + [calendar.advance(valuation_date, p, ModifiedFollowing) for p in early + core]

    # De-dup & keep only >= valuation_date
    fwd_dates = sorted({d for d in fwd_dates if d >= valuation_date})
    assert len(fwd_dates) >= 50  # at least 50 points, out to ~40y

    # Base OIS zero shape (rough, smooth, realistic enough for tests)
    def ois_zero(t_years: float) -> float:
        return (
            0.014
            + 0.010 * (1.0 - math.exp(-t_years / 2.5))
            + 0.003 * math.exp(-(((t_years - 9.0) / 5.0) ** 2))
            - 0.001 * math.exp(-(((t_years - 30.0) / 10.0) ** 2))
        )

    # Ibor instantaneous forward = OIS zero + small tenor-basis “wiggle”
    def ibor_inst_forward(t_years: float) -> float:
        basis = 0.0030 * math.exp(-t_years / 5.0) + 0.0005  # ~30bp decaying toward ~5bp
        wiggle = 0.0005 * math.exp(-(((t_years - 7.0) / 4.0) ** 2))
        return ois_zero(t_years) + basis + wiggle

    inst_fwds = [ibor_inst_forward(dc365.yearFraction(valuation_date, d)) for d in fwd_dates]

    # Forwarding term structure: reference date = first pillar (= valuation_date)
    fwd_ts = YieldTermStructureHandle(ForwardCurve(fwd_dates, inst_fwds, day_counter))
    fwd_ts.currentLink().enableExtrapolation()

    # Ibor index on this forwarding curve
    idx = IborIndex(
        "Libor",
        tenor,
        2,
        CURRENCIES[currency],
        calendar,
        ModifiedFollowing,
        False,
        day_counter,
        fwd_ts,
    )

    # ---- Populate ALL fixings (so .fixing(...) never throws) ----
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

    # All fixing dates implied by the schedule
    all_fixing_dates = sorted({idx.fixingDate(d) for d in sched.dates()})

    # Helper: compute 3M forward from DF ratio on the forwarding curve
    def fwd_from_curve(fixing_date: Date) -> float:
        start = idx.valueDate(fixing_date)  # typically T+2
        end = idx.maturityDate(start)  # start + tenor
        tau = idx.dayCounter().yearFraction(start, end)
        df_s = fwd_ts.discount(start)
        df_e = fwd_ts.discount(end)
        return (df_s / df_e - 1.0) / tau

    # Use today's forward for all past (and today) fixings curve projection for future
    today_fwd = fwd_from_curve(valuation_date)
    fix_vals = [(today_fwd if valuation_date >= F else fwd_from_curve(F)) for F in all_fixing_dates]
    idx.addFixings(tuple(all_fixing_dates), tuple(fix_vals), True)

    return idx


# ---------- full IRS ----------
@pytest.fixture
def irs(
    valuation_date,
    issue_date,
    maturity,
    tenor,
    calendar,
    day_counter,
    nominal,
    currency,
    index,
    discount_curve_handle,
):
    fixed_rate = 0.025

    fl = FloatingLeg(
        nominal=nominal,
        currency=currency,
        issue_date=issue_date,
        maturity=maturity,
        tenor=tenor,
        calendar=calendar,
        day_counter=day_counter,
        index=index,
        gearing=1.0,
        spread=0.0,
    )

    fx = FixedLeg(
        nominal=nominal,
        currency=currency,
        issue_date=issue_date,
        maturity=maturity,
        tenor=tenor,
        calendar=calendar,
        day_counter=day_counter,
        rate=fixed_rate,
    )

    return InterestRateSwap(paying_leg=fl, receiving_leg=fx, discount_curve=discount_curve_handle)


@pytest.fixture
def normal_surface_handle():
    dc = Actual365Fixed()

    # Dense option tenors (≈ up to 10Y). Include months & years.
    opt_tenors = (
        [Period("6M")] + [Period(f"{m}M") for m in (9, 12, 18)] + [Period(f"{y}Y") for y in range(2, 11)]
        # 2Y..10Y
    )

    # Dense swap tenors (1Y..30Y)
    swap_tenors = [Period(f"{y}Y") for y in range(1, 31)]

    # Build a realistic normal-vol level (50–80bp), gently term-structured
    # vols[i_opt][j_swap] must be a Matrix-like (list of lists) of floats
    vols = []
    for ot in opt_tenors:
        # convert Period to years roughly (for shaping only)
        oy = (
            (ot.length() / 12.0)
            if ot.units() == 2
            else (ot.length() / 365.0 if ot.units() == 3 else float(ot.length()))
        )
        row = []
        for st in swap_tenors:
            sy = float(st.length())  # since units are Years here
            base = 0.0065  # 65bp
            term_decay = 0.0015 * min(oy, 5.0) / 5.0  # slight ↓ with option tenor
            long_swap_decay = 0.0010 * (sy / 30.0)  # slight ↑ with swap tenor
            belly_bump = 0.0007 * (1.0 - abs(sy - 5.0) / 5.0) if 0.0 <= sy <= 10.0 else 0.0
            v = max(0.0001, base - term_decay + long_swap_decay + belly_bump)
            row.append(v)
        vols.append(row)

    # IMPORTANT: pass 'type=Normal' so Bachelier engine is happy.
    # Use the overload: (Calendar, BDC, PeriodVector, PeriodVector, Matrix vols, DayCounter, flatExtrap, type)
    surf = SwaptionVolatilityMatrix(NullCalendar(), Following, opt_tenors, swap_tenors, vols, dc, True, Normal)
    surf.enableExtrapolation()

    h = RelinkableSwaptionVolatilityStructureHandle()
    h.linkTo(surf)
    return h


@pytest.fixture
def sabr_cube(index) -> SwaptionVolatilityCube:
    dc = Actual365Fixed()
    opt_tenors = [Period("6M"), Period("1Y"), Period("2Y")]
    swap_tenors = [Period("1Y"), Period("2Y"), Period("5Y")]

    # 1) ATM surface @ 20%
    atm_quotes = [[0.20 for _ in swap_tenors] for _ in opt_tenors]
    atm = SwaptionVolatilityMatrix(NullCalendar(), Following, opt_tenors, swap_tenors, atm_quotes, dc)

    # 2) Smile spreads (rows=(opt,swap), cols=strikes) – all zeros
    strike_spreads = [-0.01, 0.0, 0.01]
    vol_spreads = []
    for _opt in opt_tenors:
        for _sw in swap_tenors:
            vol_spreads.append([QuoteHandle(SimpleQuote(0.0)) for _ in strike_spreads])

    # 3) Swap indices
    ccy = index.currency()
    cal_fix = index.fixingCalendar()
    dc_fix = Actual365Fixed()
    fixed_leg_tenor = Period("1Y")
    swap_index_base = SwapIndex(
        "GENERIC-SWAP",
        Period("10Y"),
        2,
        ccy,
        cal_fix,
        fixed_leg_tenor,
        ModifiedFollowing,
        dc_fix,
        index,
    )
    short_swap_base = SwapIndex(
        "GENERIC-SWAP-SHORT",
        Period("2Y"),
        2,
        ccy,
        cal_fix,
        fixed_leg_tenor,
        ModifiedFollowing,
        dc_fix,
        index,
    )

    # 4) SABR ctor args
    vega_weighted = False

    # IMPORTANT: order is [alpha, beta, nu, rho]
    n_rows = len(opt_tenors) * len(swap_tenors)
    parameters_guess = [
        [
            QuoteHandle(SimpleQuote(0.03)),  # alpha
            QuoteHandle(SimpleQuote(0.50)),  # beta
            QuoteHandle(SimpleQuote(0.50)),  # nu
            QuoteHandle(SimpleQuote(0.00)),
        ]  # rho
        for _ in range(n_rows)
    ]
    # Fix beta, nu, rho calibrate alpha only (since only ATM info)
    is_parameter_fixed = [False, True, True, True]
    is_atm_calibrated = True

    # Relax SABR global calibration tolerance to avoid throw on synthetic data
    end_crit = EndCriteria(1000, 200, 1e-10, 1e-10, 1e-10)
    max_error_tol = 0.10  # 10% RMS vol tolerance

    cube = SabrSwaptionVolatilityCube(
        SwaptionVolatilityStructureHandle(atm),
        opt_tenors,
        swap_tenors,
        strike_spreads,
        vol_spreads,
        swap_index_base,
        short_swap_base,
        vega_weighted,
        parameters_guess,
        is_parameter_fixed,
        is_atm_calibrated,
        end_crit,
        max_error_tol,
    )
    cube.enableExtrapolation()
    return cube


@pytest.fixture
def cube_handle(sabr_cube: SwaptionVolatilityCube):
    h = RelinkableSwaptionVolatilityStructureHandle()
    h.linkTo(sabr_cube)
    return h


def scale_cube(src_cube: SwaptionVolatilityCube, ibor_index, factor: float) -> SwaptionVolatilityCube:
    """
    Scale ATM vols and smiles by `factor`, using base-class signatures:
      atmStrike(Date, Period)   [cube overload]
      volatility(Date, Period, Rate, bool)
    """
    cal = NullCalendar()
    dc = Actual365Fixed()

    opt_tenors = list(src_cube.optionTenors())
    swap_tenors = list(src_cube.swapTenors())
    strike_spreads = list(getattr(src_cube, "strikeSpreads", lambda: [-0.01, 0.0, 0.01])())

    # ATM matrix (scaled)
    atm_matrix = []
    for opt in opt_tenors:
        row = []
        opt_date = ibor_index.fixingCalendar().advance(Settings.instance().evaluationDate, opt, ModifiedFollowing)
        for sw in swap_tenors:
            k_atm = float(src_cube.atmStrike(opt_date, sw))
            atm = float(src_cube.volatility(opt_date, sw, k_atm, True))
            row.append(atm * factor)
        atm_matrix.append(row)

    # Smile spreads (scaled)
    vol_spreads_qh = []
    for opt in opt_tenors:
        opt_date = ibor_index.fixingCalendar().advance(Settings.instance().evaluationDate, opt, ModifiedFollowing)
        for sw in swap_tenors:
            k_atm = float(src_cube.atmStrike(opt_date, sw))
            atm = float(src_cube.volatility(opt_date, sw, k_atm, True))
            row = []
            for ds in strike_spreads:
                k = k_atm + ds
                v_k = float(src_cube.volatility(opt_date, sw, k, True))
                spread = (v_k - atm) * factor
                row.append(QuoteHandle(SimpleQuote(spread)))
            vol_spreads_qh.append(row)

    # Build ATM surface
    atm_surface = SwaptionVolatilityMatrix(cal, Following, opt_tenors, swap_tenors, atm_matrix, dc)

    # Swap indices (ctor requires SwapIndex)
    ccy = ibor_index.currency()
    cal_fix = ibor_index.fixingCalendar()
    dc_fix = Actual365Fixed()
    fixed_leg_tenor = Period("1Y")
    swap_index_base = SwapIndex(
        "GENERIC-SWAP",
        Period("10Y"),
        2,
        ccy,
        cal_fix,
        fixed_leg_tenor,
        ModifiedFollowing,
        dc_fix,
        ibor_index,
    )
    short_swap_base = SwapIndex(
        "GENERIC-SWAP-SHORT",
        Period("2Y"),
        2,
        ccy,
        cal_fix,
        fixed_leg_tenor,
        ModifiedFollowing,
        dc_fix,
        ibor_index,
    )

    # SABR guesses [alpha, beta, nu, rho] fix beta, nu, rho
    n_rows = len(opt_tenors) * len(swap_tenors)
    parameters_guess = [
        [
            QuoteHandle(SimpleQuote(0.03)),
            QuoteHandle(SimpleQuote(0.50)),
            QuoteHandle(SimpleQuote(0.50)),
            QuoteHandle(SimpleQuote(0.00)),
        ]
        for _ in range(n_rows)
    ]
    is_parameter_fixed = [False, True, True, True]
    is_atm_calibrated = True

    end_crit = EndCriteria(1000, 200, 1e-10, 1e-10, 1e-10)
    max_error_tol = 0.10

    new_cube = SabrSwaptionVolatilityCube(
        SwaptionVolatilityStructureHandle(atm_surface),
        opt_tenors,
        swap_tenors,
        strike_spreads,
        vol_spreads_qh,
        swap_index_base,
        short_swap_base,
        False,  # vega_weighted
        parameters_guess,  # n_rows x 4 (alpha, beta, nu, rho)
        is_parameter_fixed,  # fix beta, nu, rho
        is_atm_calibrated,
        end_crit,
        max_error_tol,
    )
    new_cube.enableExtrapolation()
    return new_cube


def test_dump_discount_curve(discount_curve_handle, valuation_date, calendar):
    """
    Prints the curve on the fixture's pillar dates:
    date, time (yrs), discount factor, annual-compounded zero rate (%)
    """
    # Rebuild the same tenor grid as the fixture
    tenors = (
        [Period("1W"), Period("2W"), Period("3W")]
        + [Period(f"{m}M") for m in range(1, 37)]
        + [Period(f"{y}Y") for y in range(4, 41)]
    )
    dates = [calendar.advance(valuation_date, t, ModifiedFollowing) for t in tenors]
    dates = [d for d in dates if d > valuation_date]

    dc = Actual365Fixed()

    rows = []
    for d in dates:
        t = dc.yearFraction(valuation_date, d)
        df = discount_curve_handle.discount(d)
        zr = discount_curve_handle.zeroRate(d, dc, Compounded, Annual).rate() * 100.0
        rows.append({"date": d.ISO(), "t_years": t, "df": df, "zero_rate_pct": zr})

    curve = pd.DataFrame(rows).sort_values("t_years").reset_index(drop=True)

    assert (curve["df"].diff().fillna(0) <= 1e-12).all(), "DFs must be non-increasing"
    assert curve["df"].iloc[0] <= 1.0 and curve["df"].iloc[-1] >= 0.0
    assert curve["zero_rate_pct"].min() > -1.0

    # import matplotlib  # matplotlib.use("Agg")  # # headless backend for CI  # import matplotlib.pyplot as plt  #  # # Zero curve  # ax = curve.plot(x="t_years", y="zero_rate_pct", legend=False)  # ax.set_title("Zero Curve (annual-compounded)")  # ax.set_xlabel("Maturity (years)")  # ax.set_ylabel("Zero rate (%)")  # fig = ax.get_figure()  # fig.tight_layout()  # fig.savefig('Zero.png', dpi=200)  #  # # Discount factors  # ax2 = curve.plot(x="t_years", y="df", legend=False)  # ax2.set_title("Discount Factors")  # ax2.set_xlabel("Maturity (years)")  # ax2.set_ylabel("DF")  # fig2 = ax2.get_figure()  # fig2.tight_layout()  # fig2.savefig('Discount.png', dpi=200)


def test_index(index, valuation_date, issue_date, maturity, tenor, calendar):
    """
    Builds a DataFrame with one row per fixing date:
      fixing_date, start_date, end_date, accrual, forward (%), t_fix_years, t_start_years
    Uses the *index* fixture (which already has past fixings + future projections).
    Optionally saves quick pandas plots when --plot-curves is passed.
    """
    dc = Actual365Fixed()
    ts = index.forwardingTermStructure()

    # Recreate the schedule used by the fixture to get the full fixing calendar
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

    # All fixing dates implied by the schedule
    fixing_dates = sorted({index.fixingDate(d) for d in sched.dates()})

    # Helper: curve-only forward from DF ratio (what the fixture used for future fixings)
    def fwd_from_curve(fix_date):
        start = index.valueDate(fix_date)  # T+2 typically
        end = index.maturityDate(start)
        tau = index.dayCounter().yearFraction(start, end)
        df_s = ts.discount(start)
        df_e = ts.discount(end)
        return (df_s / df_e - 1.0) / tau

    # "Today's forward" used as constant for all past fixings in the fixture
    today_fwd = fwd_from_curve(valuation_date)

    rows = []
    for F in fixing_dates:
        start = index.valueDate(F)
        end = index.maturityDate(start)
        tau = index.dayCounter().yearFraction(start, end)
        fix_or_proj = index.fixing(F)  # past => stored fixing future => projection
        proj_curve = fwd_from_curve(F) if valuation_date < F else np.nan

        rows.append(
            {
                "fixing_date": F.ISO(),
                "start_date": start.ISO(),
                "end_date": end.ISO(),
                "tau": tau,
                "forward_pct": fix_or_proj * 100.0,
                "curve_proj_pct": (proj_curve * 100.0) if not math.isnan(proj_curve) else np.nan,
                "t_fix_years": dc.yearFraction(valuation_date, F),
                "t_start_years": dc.yearFraction(valuation_date, start),
                "is_past": valuation_date >= F,
            }
        )

    df = pd.DataFrame(rows).sort_values("t_fix_years").reset_index(drop=True)

    # --- Sanity checks that always run ---
    # 1) Past fixings are equal (within tiny tol) to today's forward
    past = df[df["is_past"]]
    if not past.empty:
        assert (past["forward_pct"] - today_fwd * 100.0).abs().max() < 1e-8

    # 2) For future dates, stored fixing equals curve projection (fixture does this)
    fut = df[~df["is_past"]]
    if not fut.empty:
        diff = (fut["forward_pct"] - fut["curve_proj_pct"]).abs().max()
        assert diff < 1e-8

    # 3) Rates are sane
    assert df["forward_pct"].min() > -1.0
    assert (
        df["forward_pct"].max() < 10.0
    )  # # import matplotlib  # matplotlib.use("Agg")  # import matplotlib.pyplot as plt  #  # # Forward curve vs fixing time  # ax = df.plot(x="t_fix_years", y="forward_pct", legend=False)  # ax.set_title(f"{index.name()} Forwards")  # ax.set_xlabel("Fixing time (years)")  # ax.set_ylabel("Forward rate (%)")  # fig = ax.get_figure()  # fig.tight_layout()  # p1 = "index_forward_curve.png"  # fig.savefig(p1, dpi=200)  # plt.close(fig)  #  # # Forward vs accrual start (sometimes nicer for projection intuition)  # ax2 = df.plot(x="t_start_years", y="forward_pct", legend=False)  # ax2.set_title(f"{index.name()} Forwards (by accrual start)")  # ax2.set_xlabel("Accrual start (years from valuation)")  # ax2.set_ylabel("Forward rate (%)")  # fig2 = ax2.get_figure()  # fig2.tight_layout()  # p2 = "index_forward_by_start.png"  # fig2.savefig(p2, dpi=200)  # plt.close(fig2)  #  # # Quick peek  # print('\n')  # print(df.head().to_string(index=False))  # print(f"Saved plots to:\n  {p1}\n  {p2}")


@pytest.mark.swaption_generic
class TestSwaptionGeneric:
    def test_construct_rejects_plain_structure(self, irs):
        # Not a Handle<SwaptionVolatilityStructure> → must raise
        plain = ConstantSwaptionVolatility(0, NullCalendar(), Following, 0.2, Actual365Fixed())
        with pytest.raises(TypeError):
            Swaption(irs=irs, vol_surface=plain)

    @pytest.mark.parametrize("bad_settlement", ["deliverable", "x", "", None])
    def test_rejects_bad_settlement(self, irs, cube_handle, bad_settlement):
        with pytest.raises(ValueError):
            Swaption(irs=irs, vol_surface=cube_handle, settlement=bad_settlement)

    @pytest.mark.parametrize("bad_model", ["normal", "foo", "", None])
    def test_rejects_bad_vol_model(self, irs, cube_handle, bad_model):
        with pytest.raises(ValueError):
            Swaption(irs=irs, vol_surface=cube_handle, vol_model=bad_model)

    def test_defaults_and_properties(self, irs, cube_handle, valuation_date, issue_date, currency):
        s = Swaption(irs=irs, vol_surface=cube_handle)  # defaults: physical + bachelier
        assert s.valuation_date == valuation_date
        assert s.expiry == issue_date
        assert s.strike == irs.fixed_leg.rate
        assert s.currency == irs.currency
        assert s.swaption_type() in ("payer", "receiver")

    def test_frozen_dataclass_immutable(self, irs, cube_handle):
        s = Swaption(irs=irs, vol_surface=cube_handle)
        with pytest.raises(FrozenInstanceError):
            s.is_long = False  # type: ignore[attr-defined]

    def test_long_short_sign_flip(self, irs, cube_handle):
        s_long = Swaption(irs=irs, vol_surface=cube_handle, is_long=True, vol_model="black")
        s_short = Swaption(irs=irs, vol_surface=cube_handle, is_long=False, vol_model="black")
        v_long = s_long.npv()
        v_short = s_short.npv()
        assert abs(v_long + v_short) < 1e-10

    def test_expired_returns_zero(self, irs, cube_handle, valuation_date):
        s = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            expiries=[valuation_date - 1],
            vol_model="black",
        )
        assert s.is_expired is True
        assert s.npv() == 0.0
        assert s.implied_volatility(target_npv=0.12345) == 0.0

    def test_handle_relinking_live_effect(self, irs, cube_handle, sabr_cube):
        s = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        v0 = s.npv()
        hi_cube = scale_cube(sabr_cube, irs.floating_leg.index, factor=1.3)
        cube_handle.linkTo(hi_cube)  # live relink
        v1 = s.npv()
        assert v1 >= v0 - 1e-10

    def test_accepts_surface_and_cube_handles(self, irs, normal_surface_handle, cube_handle):
        Swaption(irs=irs, vol_surface=normal_surface_handle, vol_model="bachelier")  # smoke
        Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")  # smoke

    def test_repr_doesnt_crash(self, irs, cube_handle):
        s = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        txt = repr(s)
        assert isinstance(txt, str) and len(txt) > 0


# Map model -> which vol handle fixture to use
MODEL_HANDLE = {
    "black": "cube_handle",
    "bachelier": "normal_surface_handle",
}


class TestSwaptionDomain:
    # -----------------------------
    # A) PRICING SANITY
    # -----------------------------

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_european_pricing_finite(self, request, irs, model):
        """European pricing returns finite, non-negative NPV for both models."""
        handle = request.getfixturevalue(MODEL_HANDLE[model])
        s = Swaption(irs=irs, vol_surface=handle, vol_model=model, settlement="physical")
        v = s.npv()
        assert math.isfinite(v)
        assert v >= 0.0

    def make_union_time_grid(self, irs, exercise_dates, target_steps: int = 1200, include_float: bool = True):
        """
        Build a grid with mandatory nodes at:
          - t=0
          - ALL exercise dates
          - ALL fixed-leg payment dates
          - ALL floating-leg payment dates (optional but recommended)
        Times are computed with the discount curve's timeFromReference, matching the engine.
        """
        eval_date = Settings.instance().evaluationDate
        ts = irs.discount_curve.currentLink()  # underlying term structure used by HW/tree

        def t(d):
            return float(ts.timeFromReference(d))  # guarantees exact consistency

        times = {0.0}

        # exercises
        for d in exercise_dates:
            if d > eval_date:
                x = t(d)
                if x > 0.0:
                    times.add(x)

        # coupon payment times
        v = irs.vanilla()  # keep the QL instrument alive while iterating
        for cf in v.fixedLeg():
            x = t(cf.date())
            if x > 0.0:
                times.add(x)

        if include_float:
            for cf in v.floatingLeg():
                x = t(cf.date())
                if x > 0.0:
                    times.add(x)

        mand = sorted(times)
        if len(mand) == 1:  # degenerate, just in case
            mand.append(1.0 / max(1, target_steps))

        # target_steps refines between mandatory nodes, mandatory nodes are kept verbatim
        return TimeGrid(mand, max(len(mand), int(target_steps)))

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_bermudan_ge_european(self, request, irs, model, issue_date):
        """
        Hold the HW model fixed. With the same (a, sigma) and the same tree.
        Same time grid.
        A later latest expiry increases the option price.
        """
        handle = request.getfixturevalue(MODEL_HANDLE[model])
        cal = irs.floating_leg.index.fixingCalendar()
        tenor = irs.fixed_leg.tenor
        T = cal.adjust(irs.issue_date, ModifiedFollowing)
        Tm1 = cal.adjust(T - tenor, ModifiedFollowing)
        Tm2 = cal.adjust(Tm1 - tenor, ModifiedFollowing)

        # 1) Calibrate once and reuse the parameters for all three pricings
        seed = Swaption(
            irs=irs, vol_surface=handle, vol_model=model, expiries=[T]
        )  # any expiries we just need (a, sigma)
        hw = seed._calibrate_hw()
        pars = list(hw.params())
        a, s = float(pars[0]), float(pars[1])

        # ONE Common grid for all three pricings (union of the exercise dates)
        grid = self.make_union_time_grid(irs, [Tm2, Tm1, T], target_steps=1200)

        # 2) “European via tree” (single expiry)
        s_eur = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[Tm2],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        )
        v_eur = s_eur.npv()

        # 3) Bermudan with two expiries
        s_ber1 = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[Tm2, Tm1],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        )
        v_ber1 = s_ber1.npv()

        # 4) Bermudan with three expiries
        s_ber2 = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[Tm2, Tm1, T],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        )
        v_ber2 = s_ber2.npv()

        assert v_eur <= v_ber1
        assert v_ber1 <= v_ber2

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_bermudan_removing_exercise_dates_never_increases_price(self, request, irs, model, issue_date):
        """
        Hold the HW model fixed. With the same (a, sigma) and the same tree.
        Same time grid.
        A set of expiries earlier than an utmost Common latest expiry do not change option price.
        """
        handle = request.getfixturevalue(MODEL_HANDLE[model])

        cal = irs.floating_leg.index.fixingCalendar()
        tenor = irs.fixed_leg.tenor

        T = cal.adjust(irs.issue_date, ModifiedFollowing)
        Tm1 = cal.adjust(T - tenor, ModifiedFollowing)
        Tm2 = cal.adjust(Tm1 - tenor, ModifiedFollowing)

        # Calibrate once → reuse (a, sigma)
        seed = Swaption(irs=irs, vol_surface=handle, vol_model=model, expiries=[T])
        hw = seed._calibrate_hw()
        a, s = map(float, list(hw.params())[:2])

        # ONE Common grid for all three pricings (union of the exercise dates)
        grid = self.make_union_time_grid(irs, [Tm2, Tm1, T], target_steps=1200)

        v_eur = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[T],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        ).npv()
        v_ber1 = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[Tm1, T],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        ).npv()
        v_ber2 = Swaption(
            irs=irs,
            vol_surface=handle,
            vol_model=model,
            expiries=[Tm2, Tm1, T],
            engine="hw",
            hw_a=a,
            hw_sigma=s,
            time_grid=grid,
        ).npv()

        assert abs(v_ber1 - v_eur) <= 1e-8
        assert abs(v_ber2 - v_ber1) <= 1e-8

    def test_monotonicity_in_vol(self, irs, cube_handle, sabr_cube):
        """Relinking to uniformly higher vols increases (or leaves) NPV."""
        base = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        v1 = base.npv()

        # Build a scaled (higher) cube and relink into a new handle
        h2 = RelinkableSwaptionVolatilityStructureHandle()
        h2.linkTo(scale_cube(sabr_cube, irs.floating_leg.index, 1.25))
        hi = Swaption(irs=irs, vol_surface=h2, vol_model="black")
        v2 = hi.npv()
        assert v2 >= v1 - 1e-10

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_monotonicity_in_time_to_expiry(self, request, irs, model):
        """
        For ATM, longer time-to-expiry (same swap tenor & surface) should not price lower.
        Use short = T-3M, long = T (both valid ≤ swap start).
        """
        handle = request.getfixturevalue(MODEL_HANDLE[model])

        short = Swaption(
            irs=irs,
            vol_surface=handle,
            expiries=[irs.issue_date - Period("3M")],
            vol_model=model,
        )
        long_ = Swaption(irs=irs, vol_surface=handle, expiries=[irs.issue_date], vol_model=model)
        v_short = short.npv()
        v_long = long_.npv()
        assert v_long >= v_short - 1e-10

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    @pytest.mark.parametrize("dK_bp", [-25, -10, -5, -1, 0, +1, +5, +10, +25])
    def test_receiver_vs_payer_symmetry_and_sensitivity(
        self,
        request,
        valuation_date,
        calendar,
        tenor,
        day_counter,
        currency,
        discount_curve_handle,
        model,
        nominal,
        issue_date,
        maturity,
        index,
        dK_bp,
    ):
        """
        Sweep strike shifts ΔK in basis points around par.
        Assert the expected monotonicity for payer/receiver swaptions.
        """
        handle = request.getfixturevalue(MODEL_HANDLE[model])

        # Build ATM IRS first (fixed = fair)
        fl = FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            index=index,
            gearing=1.0,
            spread=0.0,
        )
        fx_tmp = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=0.0,
        )
        irs_tmp = InterestRateSwap(paying_leg=fl, receiving_leg=fx_tmp, discount_curve=discount_curve_handle)
        fair = irs_tmp.vanilla().fairRate()

        # ATM payer/receiver swaptions (expiry at swap start)
        payer_atm = InterestRateSwap(
            paying_leg=FixedLeg(
                nominal=nominal,
                currency=currency,
                issue_date=issue_date,
                maturity=maturity,
                tenor=tenor,
                calendar=calendar,
                day_counter=day_counter,
                rate=fair,
            ),
            receiving_leg=fl,
            discount_curve=discount_curve_handle,
        )
        receiver_atm = InterestRateSwap(
            paying_leg=fl,
            receiving_leg=FixedLeg(
                nominal=nominal,
                currency=currency,
                issue_date=issue_date,
                maturity=maturity,
                tenor=tenor,
                calendar=calendar,
                day_counter=day_counter,
                rate=fair,
            ),
            discount_curve=discount_curve_handle,
        )

        sp0 = Swaption(irs=payer_atm, vol_surface=handle, vol_model=model, expiries=[issue_date]).npv()
        sr0 = Swaption(irs=receiver_atm, vol_surface=handle, vol_model=model, expiries=[issue_date]).npv()

        dK = dK_bp * 1e-4  # convert bp to rate

        # Build ±ΔK swaps
        fx_shift = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=fair + dK,
        )
        payer_shifted = InterestRateSwap(paying_leg=fx_shift, receiving_leg=fl, discount_curve=discount_curve_handle)
        receiver_shifted = InterestRateSwap(paying_leg=fl, receiving_leg=fx_shift, discount_curve=discount_curve_handle)

        sp = Swaption(
            irs=payer_shifted,
            vol_surface=handle,
            vol_model=model,
            expiries=[issue_date],
        ).npv()
        sr = Swaption(
            irs=receiver_shifted,
            vol_surface=handle,
            vol_model=model,
            expiries=[issue_date],
        ).npv()

        eps = 1e-10
        if dK > 0:
            assert sp <= sp0 + eps  # payer ↓ with lower strike
            assert sr >= sr0 - eps  # receiver ↑ with lower strike
        elif dK < 0:
            assert sp >= sp0 - eps  # payer ↑ with higher strike
            assert sr <= sr0 + eps  # receiver ↓ with higher strike
        else:
            # dK == 0 → essentially equal
            assert abs(sp - sp0) <= max(1e-8, 1e-6 * max(1.0, abs(sp0)))
            assert abs(sr - sr0) <= max(1e-8, 1e-6 * max(1.0, abs(sr0)))

    # -----------------------------
    # B) MODEL SELECTION & ENGINES
    # -----------------------------

    def test_engine_chosen_by_model(self, irs, cube_handle, normal_surface_handle):
        # Black → BlackSwaptionEngine
        s_black = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        eng_b = s_black._engine_european()
        assert isinstance(eng_b, BlackSwaptionEngine)

        # Bachelier → BachelierSwaptionEngine
        s_norm = Swaption(irs=irs, vol_surface=normal_surface_handle, vol_model="bachelier")
        eng_n = s_norm._engine_european()
        assert isinstance(eng_n, BachelierSwaptionEngine)

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_implied_vol_reprices(self, request, irs, model):
        """
        implied_volatility(price) returns an implied vol that reprices with a constant-vol engine.
        """
        h = request.getfixturevalue(MODEL_HANDLE[model])
        s = Swaption(irs=irs, vol_surface=h, vol_model=model)
        target = s.npv()
        vol = s.implied_volatility(target)

        # Reprice with constant-vol engine using that volatility
        v = s.irs.vanilla()
        ql_swaption = QLSwaption(v, EuropeanExercise(s.expiry), Settlement.Physical)
        dh = s.irs.discount_curve

        if model == "bachelier":
            ql_swaption.setPricingEngine(BachelierSwaptionEngine(dh, QuoteHandle(SimpleQuote(vol)), h.dayCounter()))
        else:
            # Use shift from the surface if available
            surf = s.vol_surface.currentLink()
            opt_date = s.irs.floating_leg.index.fixingCalendar().adjust(s.expiry, ModifiedFollowing)
            v = irs.vanilla()  # needed to keep other variable alive else C++ crash
            sch = v.fixedSchedule()
            months = 12 * (sch.endDate().year() - sch.startDate().year()) + (
                int(sch.endDate().month()) - int(sch.startDate().month())
            )
            swap_len = Period(max(1, months), Months)
            try:
                shift = float(surf.shift(opt_date, swap_len))
            except Exception:
                shift = 0.0
            ql_swaption.setPricingEngine(
                BlackSwaptionEngine(dh, QuoteHandle(SimpleQuote(vol)), h.dayCounter(), float(shift))
            )

        got = float(ql_swaption.NPV())
        assert abs(got - target) <= max(1e-8, 1e-6 * max(1.0, abs(target)))

    # -----------------------------
    # C) VOL SURFACE / CUBE INTEGRATION
    # -----------------------------

    def test_handle_relinking_changes_npv(self, irs, cube_handle, sabr_cube):
        s1 = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        v1 = s1.npv()

        h2 = RelinkableSwaptionVolatilityStructureHandle()
        h2.linkTo(scale_cube(sabr_cube, irs.floating_leg.index, 0.80))  # lower vols
        s2 = Swaption(irs=irs, vol_surface=h2, vol_model="black")
        v2 = s2.npv()
        assert v2 <= v1 + 1e-10

    def test_cube_capabilities_present(self, sabr_cube, index):
        # Ensure cube APIs are callable and coherent at a sample node
        opt = list(sabr_cube.optionTenors())[0]
        sw = list(sabr_cube.swapTenors())[0]
        opt_date = index.fixingCalendar().advance(Settings.instance().evaluationDate, opt, ModifiedFollowing)
        k = float(sabr_cube.atmStrike(opt_date, sw))
        v = float(sabr_cube.volatility(opt_date, sw, k, True))
        sh = float(sabr_cube.shift(opt_date, sw))
        assert v > 0.0
        assert sh >= 0.0

    def test_date_vs_tenor_queries_equivalent(self, sabr_cube, index):
        """
        Compare date-based vs tenor-based volatility queries at the same node.
        Skip if the tenor overload isn't available in this QL build.
        """
        cube = sabr_cube

        # Pick a grid node
        opt = list(cube.optionTenors())[0]
        sw = list(cube.swapTenors())[0]
        opt_date = index.fixingCalendar().advance(Settings.instance().evaluationDate, opt, ModifiedFollowing)
        # ATM strike and date-based vol
        k_atm_d = float(cube.atmStrike(opt_date, sw))
        v_date = float(cube.volatility(opt_date, sw, k_atm_d, True))

        # Shift: try tenor-based first, else date-based
        try:
            shift = float(cube.shift(opt, sw))
        except TypeError:
            shift = float(cube.shift(opt_date, sw))

        # Tenor-based overload may not be exposed try and skip if not
        try:
            v_tenor = float(cube.volatility(opt, sw, k_atm_d, ShiftedLognormal, shift))
        except TypeError:
            pytest.skip("Tenor-based volatility overload not available in this QuantLib build.")
            return

        assert abs(v_date - v_tenor) < 1e-8

    # -----------------------------
    # D) CURVES, FIXINGS, CALENDARS
    # -----------------------------

    def test_fixing_coverage_never_throws(self, index, issue_date, maturity, tenor, calendar):
        """All fixing dates implied by the swap schedule are retrievable."""
        sch = Schedule(
            issue_date,
            maturity,
            tenor,
            calendar,
            ModifiedFollowing,
            Preceding,
            DateGeneration.Forward,
            False,
        )
        for d in sch.dates():
            f = index.fixingDate(d)
            _ = index.fixing(f)  # should not throw

    def test_discounting_consistency_in_atm(self, irs, normal_surface_handle, valuation_date):
        """Changing the discount curve should change the ATM strike computed via SwapIndex."""
        s = Swaption(irs=irs, vol_surface=normal_surface_handle, vol_model="bachelier")
        opt = Period("6M")
        # use exact swap length logic from your implied-vol routine
        v = irs.vanilla()  # needed to keep other variable alive else C++ crash
        sch = v.fixedSchedule()
        months = 12 * (sch.endDate().year() - sch.startDate().year()) + (
            int(sch.endDate().month()) - int(sch.startDate().month())
        )
        sw = Period(max(1, months), Months)
        k1 = s._atm_strike_for(opt, sw)

        # Rebuild IRS with a bumped flat discount curve (same index)
        dc = Actual365Fixed()
        bumped = YieldTermStructureHandle(FlatForward(irs.valuation_date, QuoteHandle(SimpleQuote(0.0050)), dc))
        irs_bump = InterestRateSwap(
            paying_leg=irs.paying_leg,
            receiving_leg=irs.receiving_leg,
            discount_curve=bumped,
        )
        s2 = Swaption(irs=irs_bump, vol_surface=normal_surface_handle, vol_model="bachelier")
        k2 = s2._atm_strike_for(opt, sw)
        assert abs(k2 - k1) > 1e-10

    def test_expiry_adjusted_to_business_day(self, index, irs, issue_date, cube_handle):
        """Expiry on a weekend adjusts to business day and prices fine (and ≤ swap start)."""
        cal = index.fixingCalendar()

        # Choose a Saturday BEFORE the swap start
        exp = irs.issue_date
        while exp.weekday() != 6:  # 6 = Saturday in QuantLib
            exp = exp - 1  # go backwards day by day

        # Adjust (ModifiedFollowing moves Saturday -> next Monday)
        adj = cal.adjust(exp, ModifiedFollowing)

        # Sanity: adjusted business day and still on/before the swap start
        assert cal.isBusinessDay(adj)
        assert adj <= irs.issue_date

        # Price: now the engine is happy
        s = Swaption(irs=irs, vol_surface=cube_handle, expiries=[exp], vol_model="black")
        assert math.isfinite(s.npv())

    # -----------------------------
    # E) CALIBRATION (BERMUDAN PATH)
    # -----------------------------

    def test_hw_calibration_returns_finite(self, irs, cube_handle):
        """_calibrate_hw returns finite params Bermudan NPV finite."""
        # 2 exercise dates (≤ swap start)
        exps = [irs.issue_date - Period("3M"), irs.issue_date]
        sw = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black", expiries=exps)
        model = sw._calibrate_hw()

        a, s = map(float, list(model.params())[:2])

        assert math.isfinite(a) and a >= 0.0
        assert math.isfinite(s) and s >= 0.0

        v_ber = sw.npv()  # Tree engine path is used
        assert math.isfinite(v_ber)

    def test_hw_basket_sensitivity_smooth(self, irs, cube_handle, issue_date, valuation_date):
        """
        Change the calibration basket (use 2 helpers manually) and ensure
        Bermudan NPV stays reasonable vs default calibration.
        """
        # Default via class (uses its own basket)
        exps = [irs.issue_date - Period("3M"), irs.issue_date]
        s_def = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            vol_model="black",
            expiries=exps,
            engine="hw",
        )
        v_def = s_def.npv()

        # Manual tiny-basket calibration to get (a, sigma)
        surf = cube_handle.currentLink()
        idx = irs.floating_leg.index
        dh = irs.discount_curve
        dc_fix = irs.fixed_leg.day_counter
        dc_flt = irs.floating_leg.day_counter
        fixed_tenor = irs.fixed_leg.tenor
        vt = ShiftedLognormal

        model_alt = HullWhite(dh)
        eng_alt = JamshidianSwaptionEngine(model_alt)

        st = s_def._required_swap_len_period()  # swap tenor of the underlying (in months → Period)
        basket = [(Period("6M"), st), (Period("1Y"), st), (Period("2Y"), st)]
        helpers = []
        for ot, st in basket:
            # ATM strike via your helper (multi-curve consistent)
            k_atm = Swaption(irs=irs, vol_surface=cube_handle)._atm_strike_for(ot, st)
            # Vol via (Date, Period, strike, extrap=True)
            opt_date = idx.fixingCalendar().advance(irs.valuation_date, ot, ModifiedFollowing)
            vol = float(surf.volatility(opt_date, st, k_atm, True))
            q = QuoteHandle(SimpleQuote(vol))

            h = SwaptionHelper(
                ot,  # maturity (option tenor)
                st,  # length   (swap tenor)
                q,  # QuoteHandle(vol)
                idx,  # IborIndex (forwarding curve)
                fixed_tenor,  # fixed leg tenor
                dc_fix,  # fixed leg day counter
                dc_flt,  # float leg day counter
                dh,  # discount curve
                BlackCalibrationHelper.RelativePriceError,
                k_atm,  # strike (use ATM)
                1.0,  # nominal
                vt,  # VolatilityType (ShiftedLognormal here)
                0.0,  # shift (0 if your cube has no displacement)
            )
            h.setPricingEngine(eng_alt)
            helpers.append(h)

        method = LevenbergMarquardt()
        end = EndCriteria(500, 100, 1e-12, 1e-12, 1e-12)
        model_alt.calibrate(helpers, method, end)

        a_alt, s_alt = map(float, list(model_alt.params())[:2])

        # Price the Bermudan with the alt parameters using YOUR class
        s_alt = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            vol_model="black",
            expiries=exps,
            engine="hw",
            hw_a=a_alt,
            hw_sigma=s_alt,
            hw_time_steps=80,
        )
        v_alt = s_alt.npv()

        assert math.isfinite(v_alt)
        # Loose but meaningful bound: “smoothness” vs default calibration
        assert abs(v_alt - v_def) / abs(v_def) < 0.25

    # -----------------------------
    # F) EDGE / ROBUSTNESS
    # -----------------------------

    def test_pricing_with_extreme_vols_is_finite_black_and_bachelier(self, irs):
        dc = Actual365Fixed()
        opt_tenors = [Period("6M"), Period("1Y"), Period("2Y")]
        swap_tenors = [Period("1Y"), Period("5Y"), Period("10Y")]

        # --- Black with very high vol (200%)
        vols_hi = Matrix(len(opt_tenors), len(swap_tenors), 2.0)
        surf_hi = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols_hi,
            dc,
            True,
            ShiftedLognormal,
        )
        h_hi = RelinkableSwaptionVolatilityStructureHandle()
        h_hi.linkTo(surf_hi)
        s_hi = Swaption(irs=irs, vol_surface=h_hi, vol_model="black")
        v_hi = s_hi.npv()
        assert math.isfinite(v_hi) and v_hi >= 0.0

        # --- Black with ultra low vol (~1e-6)
        vols_lo = Matrix(len(opt_tenors), len(swap_tenors), 1e-6)
        surf_lo = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols_lo,
            dc,
            True,
            ShiftedLognormal,
        )
        h_lo = RelinkableSwaptionVolatilityStructureHandle()
        h_lo.linkTo(surf_lo)
        s_lo = Swaption(irs=irs, vol_surface=h_lo, vol_model="black")
        v_lo = s_lo.npv()
        assert math.isfinite(v_lo) and v_lo >= 0.0

        # --- Bachelier (Normal) with high absolute normal vol (10%)
        vols_n_hi = Matrix(len(opt_tenors), len(swap_tenors), 0.10)
        surf_n_hi = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols_n_hi,
            dc,
            True,
            Normal,
        )
        h_n_hi = RelinkableSwaptionVolatilityStructureHandle()
        h_n_hi.linkTo(surf_n_hi)
        s_n_hi = Swaption(irs=irs, vol_surface=h_n_hi, vol_model="bachelier")
        v_n_hi = s_n_hi.npv()
        assert math.isfinite(v_n_hi) and v_n_hi >= 0.0

        # --- Bachelier with ultra low normal vol
        vols_n_lo = Matrix(len(opt_tenors), len(swap_tenors), 1e-6)
        surf_n_lo = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols_n_lo,
            dc,
            True,
            Normal,
        )
        h_n_lo = RelinkableSwaptionVolatilityStructureHandle()
        h_n_lo.linkTo(surf_n_lo)
        s_n_lo = Swaption(irs=irs, vol_surface=h_n_lo, vol_model="bachelier")
        v_n_lo = s_n_lo.npv()
        assert math.isfinite(v_n_lo) and v_n_lo >= 0.0

    def test_implied_vol_bounds_respected(self, irs, cube_handle):
        """implied_volatility respects [min_vol, max_vol] and returns a bounded value."""
        s = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        price = s.npv()
        iv = s.implied_volatility(price, min_vol=1e-6, max_vol=2.0)
        assert 1e-6 <= iv <= 2.0

    def test_near_expiry_zero_price_and_zero_impv(self, irs, cube_handle, valuation_date):
        """If evaluationDate >= expiry → NPV=0 and implied vol returns 0."""
        # Force expiry today (or earlier)
        s = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            expiries=[irs.valuation_date - 1],
            vol_model="black",
        )
        assert s.is_expired is True
        assert s.npv() == 0.0
        assert s.implied_volatility(0.0) == 0.0

    def test_non_atm_directional_payer_receiver(
        self,
        valuation_date,
        calendar,
        tenor,
        day_counter,
        currency,
        discount_curve_handle,
        index,
        maturity,
        nominal,
        normal_surface_handle,
        issue_date,
    ):
        """Directional sanity: payer call ↑ when strike ↓ receiver put ↑ when strike ↑."""
        # Build ATM IRS (strike set to fair)

        issue_date = valuation_date + Period("3M")  # swap starts in the future
        fl = FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            index=index,
            gearing=1.0,
            spread=0.0,
        )
        fx_tmp = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=0.0,
        )
        irs_tmp = InterestRateSwap(paying_leg=fl, receiving_leg=fx_tmp, discount_curve=discount_curve_handle)
        fair = irs_tmp.vanilla().fairRate()

        # Payer swaption (call on swap rate)
        fx_payer_lo = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=fair - 0.0005,
        )  # K↓
        irs_payer_lo = InterestRateSwap(
            paying_leg=fx_payer_lo,
            receiving_leg=fl,
            discount_curve=discount_curve_handle,
        )
        fx_payer_hi = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=fair + 0.0005,
        )  # K↑
        irs_payer_hi = InterestRateSwap(
            paying_leg=fx_payer_hi,
            receiving_leg=fl,
            discount_curve=discount_curve_handle,
        )

        sp_lo = Swaption(
            irs=irs_payer_lo,
            vol_surface=normal_surface_handle,
            vol_model="bachelier",
            expiries=[issue_date],
        )
        sp_hi = Swaption(
            irs=irs_payer_hi,
            vol_surface=normal_surface_handle,
            vol_model="bachelier",
            expiries=[issue_date],
        )

        assert sp_lo.npv() >= sp_hi.npv() - 1e-10  # call ↑ when K ↓

        # Receiver swaption (put on swap rate)
        irs_recv_lo = InterestRateSwap(
            paying_leg=fl,
            receiving_leg=fx_payer_lo,
            discount_curve=discount_curve_handle,
        )
        irs_recv_hi = InterestRateSwap(
            paying_leg=fl,
            receiving_leg=fx_payer_hi,
            discount_curve=discount_curve_handle,
        )
        sr_lo = Swaption(
            irs=irs_recv_lo,
            vol_surface=normal_surface_handle,
            vol_model="bachelier",
            expiries=[issue_date],
        )
        sr_hi = Swaption(
            irs=irs_recv_hi,
            vol_surface=normal_surface_handle,
            vol_model="bachelier",
            expiries=[issue_date],
        )

        assert sr_hi.npv() >= sr_lo.npv() - 1e-10  # put ↑ when K ↑

    def test_negative_rates_with_bachelier_run_and_solve(self, valuation_date, maturity):
        """
        Build a tiny world with negative forwards/zeros and check that
        Bachelier pricing + implied vol works.
        """
        # Basic env
        cal = TARGET()
        dc = Actual360()
        currency = "SEK"
        tenor = Period("3M")
        nominal = 100_000_000.0

        # Discount curve: flat -0.25%
        disc = YieldTermStructureHandle(
            FlatForward(valuation_date, QuoteHandle(SimpleQuote(-0.0025)), Actual365Fixed())
        )
        disc.currentLink().enableExtrapolation()

        # Forward curve: dense pillars, flat -0.10% inst fwd
        tenors = (
            [Period("1D"), Period("2D")]
            + [Period("1W"), Period("2W"), Period("3W")]
            + [Period(f"{m}M") for m in range(1, 37)]
            + [Period(f"{y}Y") for y in range(4, 41)]
        )
        fwd_dates = [valuation_date] + [cal.advance(valuation_date, t, ModifiedFollowing) for t in tenors]
        fwd_dates = sorted(set(d for d in fwd_dates if d >= valuation_date))
        fwds = [-0.001 for _ in fwd_dates]
        fwd_ts = YieldTermStructureHandle(ForwardCurve(fwd_dates, fwds, dc))
        fwd_ts.currentLink().enableExtrapolation()

        # Ibor index on this forwarding curve
        idx = IborIndex(
            "Libor",
            tenor,
            2,
            CURRENCIES[currency],
            cal,
            ModifiedFollowing,
            False,
            dc,
            fwd_ts,
        )

        # Fill all fixings for a small swap horizon
        issue = valuation_date + Period("3M")
        maturity = valuation_date + Period("5Y")
        sched = Schedule(
            issue,
            maturity,
            tenor,
            cal,
            ModifiedFollowing,
            ModifiedFollowing,
            DateGeneration.Forward,
            False,
        )
        all_fixing_dates = sorted({idx.fixingDate(d) for d in sched.dates()})

        def fwd_from_curve(F):
            start = idx.valueDate(F)
            end = idx.maturityDate(start)
            tau = idx.dayCounter().yearFraction(start, end)
            return (fwd_ts.discount(start) / fwd_ts.discount(end) - 1.0) / tau

        today_fwd = fwd_from_curve(valuation_date)
        vals = [today_fwd if valuation_date >= F else fwd_from_curve(F) for F in all_fixing_dates]
        idx.addFixings(tuple(all_fixing_dates), tuple(vals), True)

        # Build an IRS (par strike will be slightly negative)
        fl = FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue,
            maturity=maturity,
            tenor=tenor,
            calendar=cal,
            day_counter=dc,
            index=idx,
            gearing=1.0,
            spread=0.0,
        )
        fx_tmp = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue,
            maturity=maturity,
            tenor=tenor,
            calendar=cal,
            day_counter=dc,
            rate=0.0,
        )
        irs_tmp = InterestRateSwap(paying_leg=fl, receiving_leg=fx_tmp, discount_curve=disc)
        fair = irs_tmp.vanilla().fairRate()  # should be ≤ 0 in this setup

        fx = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue,
            maturity=maturity,
            tenor=tenor,
            calendar=cal,
            day_counter=dc,
            rate=fair,
        )
        irs = InterestRateSwap(paying_leg=fx, receiving_leg=fl, discount_curve=disc)

        # Normal surface (Bachelier), e.g. 60bp normal vol
        opt_tenors = [Period("6M"), Period("1Y"), Period("2Y")]
        swap_tenors = [Period("1Y"), Period("2Y"), Period("5Y")]
        vols = Matrix(len(opt_tenors), len(swap_tenors), 0.006)
        surf = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols,
            Actual365Fixed(),
            True,
            Normal,
        )
        h = RelinkableSwaptionVolatilityStructureHandle()
        h.linkTo(surf)

        # Price & implied vol under Bachelier
        s = Swaption(irs=irs, vol_surface=h, vol_model="bachelier", expiries=[issue])
        price = s.npv()
        assert math.isfinite(price) and price >= 0.0
        iv = s.implied_volatility(price)
        assert iv > 0.0

    # -----------------------------
    # G) REGRESSION / DETERMINISM
    # -----------------------------

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_prices_deterministic_across_runs(self, request, irs, model):
        handle = request.getfixturevalue(MODEL_HANDLE[model])
        s1 = Swaption(irs=irs, vol_surface=handle, vol_model=model)
        s2 = Swaption(irs=irs, vol_surface=handle, vol_model=model)
        v1 = s1.npv()
        v2 = s2.npv()
        assert v1 == v2  # pure functions w/ fixed fixtures

    @pytest.mark.parametrize("model", ["black", "bachelier"])
    def test_implied_vol_deterministic_across_runs(self, request, irs, model):
        handle = request.getfixturevalue(MODEL_HANDLE[model])
        s = Swaption(irs=irs, vol_surface=handle, vol_model=model)
        price = s.npv()
        iv1 = s.implied_volatility(price)
        iv2 = s.implied_volatility(price)
        assert iv1 == iv2


GOLDEN = {
    "env": {  # Optional: pin to the QL version you used to record the numbers.
        # If this mismatches in CI, we skip rather than fail noisy.
        "quantlib_version": None,  # e.g. "1.33"
    },
    "black": {
        "npv": 1090133.851197490468621,  # e.g. 771764.1956050845
        "iv": 0.1753831280,  # e.g. 0.2054321
        # tolerances: keep them tight but realistic across OS/compilers
        "abs_tol": 2.0,  # currency units
        "rel_tol": 5e-6,  # ~5 ppm relative
    },
    "bachelier": {
        "npv": 1785483.107085254509002,  # e.g. 1860522.4217513355
        "iv": 0.0065333333,  # e.g. 0.00673  (normal vol)
        "abs_tol": 2.0,
        "rel_tol": 5e-6,
    },
}


def _approx_eq(x, target, abs_tol, rel_tol):
    # like math.isclose but both tolerances always applied
    return abs(x - target) <= max(abs_tol, rel_tol * max(1.0, abs(target)))


class TestSwaptionGolden:
    @pytest.mark.skipif(
        GOLDEN["env"]["quantlib_version"] is not None
        and getattr(__import__("QuantLib"), "QL_VERSION_STR", None) != GOLDEN["env"]["quantlib_version"],
        reason="QuantLib version mismatch with recorded golden numbers",
    )
    def test_golden_numbers(self, irs, cube_handle, normal_surface_handle):
        """
        Golden NPV & IV for European payer/receiver (single-expiry at issue_date).
        Fill GOLDEN[...] constants from one local run keep tolerances tight but not brittle.
        """
        # Black (lognormal / cube)
        s_b = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        v_b = s_b.npv()
        iv_b = s_b.implied_volatility(v_b)

        # Bachelier (normal)
        s_n = Swaption(irs=irs, vol_surface=normal_surface_handle, vol_model="bachelier")
        v_n = s_n.npv()
        iv_n = s_n.implied_volatility(v_n)

        # If you haven't filled values yet, print once then fail with guidance.
        if any(GOLDEN[k]["npv"] is None or GOLDEN[k]["iv"] is None for k in ("black", "bachelier")):
            import QuantLib as ql

            print("\n=== RECORD THESE GOLDEN NUMBERS ===")
            print(f"QuantLib version: {getattr(ql, 'QL_VERSION_STR', 'unknown')}")
            print(f"Black     NPV = {v_b:.15f},  IV = {iv_b:.10f}")
            print(f"Bachelier NPV = {v_n:.15f},  IV = {iv_n:.10f}")
            pytest.fail("Fill GOLDEN[...] with the printed values and set an optional QuantLib version.")

        # ---- Assertions (NPV & IV) ----
        gb = GOLDEN["black"]
        gn = GOLDEN["bachelier"]

        assert _approx_eq(v_b, gb["npv"], gb["abs_tol"], gb["rel_tol"]), f"Black NPV {v_b} != golden {gb['npv']}"
        assert _approx_eq(iv_b, gb["iv"], 1e-10, 5e-8), f"Black IV  {iv_b} != golden {gb['iv']}"

        assert _approx_eq(v_n, gn["npv"], gn["abs_tol"], gn["rel_tol"]), f"Bachelier NPV {v_n} != golden {gn['npv']}"
        assert _approx_eq(iv_n, gn["iv"], 1e-10, 5e-8), f"Bachelier IV  {iv_n} != golden {gn['iv']}"


class TestSwaptionExpiryAndCoverage:
    def test_zero_value_on_and_after_expiry(self, irs, cube_handle, calendar, issue_date):
        """
        Price should be 0.0 if valuation is on/after expiry.
        """
        s = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            vol_model="black",
            expiries=[irs.issue_date - 1],
        )

        # save & restore eval date
        settings = Settings.instance()
        eval0 = settings.evaluationDate

        try:
            # On expiry
            settings.evaluationDate = irs.issue_date
            assert s.is_expired is True
            assert s.npv() == 0.0
            assert s.implied_volatility(0.0) == 0.0

            # After expiry (next business day)
            settings.evaluationDate = calendar.advance(irs.issue_date, Period("1D"), ModifiedFollowing)
            assert s.is_expired is True
            assert s.npv() == 0.0
            assert s.implied_volatility(0.0) == 0.0
        finally:
            settings.evaluationDate = eval0

    def test_zero_value_after_swap_maturity(self, irs, cube_handle, calendar, issue_date):
        """
        Even if you move valuation after the swap maturity, the swaption has long expired → 0.0.
        """
        s = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            vol_model="black",
            expiries=[irs.issue_date],
        )

        settings = Settings.instance()
        eval0 = settings.evaluationDate
        try:
            after_maturity = calendar.advance(irs.receiving_leg.maturity, Period("1D"), ModifiedFollowing)
            settings.evaluationDate = after_maturity
            assert s.is_expired is True
            assert s.npv() == 0.0
            assert s.implied_volatility(0.0) == 0.0
        finally:
            settings.evaluationDate = eval0

    def test_curve_horizon_validation_raises_without_extrapolation(
        self,
        valuation_date,
        calendar,
        day_counter,
        currency,
        tenor,
        nominal,
        issue_date,
        maturity,
    ):
        """
        Build an IRS whose swap goes well beyond a deliberately short index forwarding curve
        (with extrapolation DISABLED). Swaption construction should raise in __post_init__.
        """
        # --- Short forward curve (max ~1Y), DO NOT enable extrapolation
        tenors_short = [
            Period("1M"),
            Period("3M"),
            Period("6M"),
            Period("9M"),
            Period("12M"),
        ]
        fwd_dates = [calendar.advance(valuation_date, p, ModifiedFollowing) for p in tenors_short]
        fwd_dates = sorted(set([valuation_date] + fwd_dates))
        fwds = [0.02 for _ in fwd_dates]  # arbitrary inst fwds
        short_fwd = YieldTermStructureHandle(ForwardCurve(fwd_dates, fwds, day_counter))
        # (no extrapolation on purpose)

        # --- Discount curve long enough enable extrapolation so failure isolates to fwd TS
        disc = YieldTermStructureHandle(FlatForward(valuation_date, QuoteHandle(SimpleQuote(0.02)), Actual365Fixed()))
        disc.currentLink().enableExtrapolation()

        # --- Long-dated swap (10Y) starting in 3M → required end >> short_fwd.maxDate
        issue_date = calendar.advance(valuation_date, Period("3M"), ModifiedFollowing)
        maturity = calendar.advance(issue_date, Period("10Y"), ModifiedFollowing)

        # --- Minimal vol surface (type doesn’t matter for this test)
        opt_tenors = [Period("6M"), Period("1Y")]
        swap_tenors = [Period("5Y"), Period("10Y")]
        vols = Matrix(len(opt_tenors), len(swap_tenors), 0.01)
        surf = SwaptionVolatilityMatrix(
            NullCalendar(),
            Following,
            opt_tenors,
            swap_tenors,
            vols,
            Actual365Fixed(),
            True,
            ShiftedLognormal,
        )
        h_vol = RelinkableSwaptionVolatilityStructureHandle()
        h_vol.linkTo(surf)

        # --- Ibor index with the SHORT forwarding curve
        # NOTE: pass positionally and use a QuantLib Currency object
        idx = IborIndex(
            "Libor",
            tenor,
            2,  # fixing days
            CURRENCIES[currency],  # QuantLib Currency, not a string
            calendar,
            ModifiedFollowing,
            False,  # end-of-month
            day_counter,
            short_fwd,  # forwarding term structure
        )

        # Minimal fixings (won't be used constructor should fail first)
        sched = Schedule(
            issue_date,
            maturity,
            tenor,
            calendar,
            ModifiedFollowing,
            ModifiedFollowing,
            DateGeneration.Forward,
            False,
        )
        fixing_dates = sorted({idx.fixingDate(d) for d in sched.dates()})
        if fixing_dates:
            idx.addFixings(tuple(fixing_dates), tuple([0.02] * len(fixing_dates)), True)

        # --- Build IRS with this index
        fl = FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            index=idx,
            gearing=1.0,
            spread=0.0,
        )
        fx = FixedLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            rate=0.025,
        )
        irs_long = InterestRateSwap(paying_leg=fl, receiving_leg=fx, discount_curve=disc)

        # Constructing the swaption MUST raise due to short forwarding curve horizon
        with pytest.raises(
            ValueError,
            match="forwarding curve too short|Index forwarding curve too short",
        ):
            _ = Swaption(
                irs=irs_long,
                vol_surface=h_vol,
                vol_model="black",
                expiries=[issue_date],
            )


@pytest.mark.swaption_generic
class TestHugues:
    def test_accepts_surface_handle(self, irs):
        ok = SwaptionVolatilityStructureHandle(
            ConstantSwaptionVolatility(0, NullCalendar(), Following, 0.2, Actual365Fixed())
        )
        Swaption(irs=irs, vol_surface=ok)  # should NOT raise

    def test_euro_monotone_in_vol(self, irs, cube_handle, sabr_cube):
        swaption = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black", settlement="physical")
        v1 = swaption.npv()

        # Relink to a higher cube (scale vols 1.5x)
        h2 = RelinkableSwaptionVolatilityStructureHandle()
        h2.linkTo(scale_cube(sabr_cube, swaption.irs.floating_leg.index, 1.5))  # pass the CONCRETE cube
        swaption_hi = Swaption(irs=irs, vol_surface=h2, vol_model="black", settlement="physical")

        v2 = swaption_hi.npv()

        print("\n")
        print("v2", v2)
        print("v1", v1)

        assert v2 >= v1 - 1e-10

    def test_bermudan_ge_european_black(self, irs, cube_handle, issue_date):
        s_eur = Swaption(
            irs=irs,
            vol_surface=cube_handle,
            expiries=[irs.issue_date - Period("6M")],
            vol_model="black",
        )
        v_eur = s_eur.npv()

        exps = [irs.issue_date, irs.issue_date - Period("6M")]
        s_ber = Swaption(irs=irs, vol_surface=cube_handle, expiries=exps, vol_model="black")
        v_ber = s_ber.npv()

        print("\n")
        print("v_eur", v_eur)
        print("v_ber", v_ber)

        assert v_ber >= v_eur - 1e-10

    def test_bermudan_ge_european_bachelier(self, irs, issue_date, normal_surface_handle):
        s_eur = Swaption(
            irs=irs,
            vol_surface=normal_surface_handle,
            expiries=[irs.issue_date],
            vol_model="bachelier",
        )
        v_eur = s_eur.npv()

        exps = [irs.issue_date, irs.issue_date + Period("6M")]
        s_ber = Swaption(
            irs=irs,
            vol_surface=normal_surface_handle,
            expiries=exps,
            vol_model="bachelier",
        )
        v_ber = s_ber.npv()

        print("\n")
        print("v_eur", v_eur)
        print("v_ber", v_ber)

        assert v_ber >= v_eur - 1e-10

    def test_implied_vol_black(self, irs, cube_handle):
        s = Swaption(irs=irs, vol_surface=cube_handle, vol_model="black")
        price = s.npv()
        vol = s.implied_volatility(price)
        print("\n")
        print("irs mtm: ", irs.npv())
        print("swap price: ", price)
        print("swap ty: ", s.swaption_type())
        print("swap exec day:", s._expiries())
        print("Is exprired:", s.is_expired)
        print("Implied Vol: ", vol)
        assert price > 0.0
        assert vol > 0.0

    def test_implied_vol_bachelier(self, irs, normal_surface_handle):
        s = Swaption(irs=irs, vol_surface=normal_surface_handle, vol_model="bachelier")
        price = s.npv()
        vol = s.implied_volatility(price)
        print("\n")
        print("irs mtm: ", irs.npv())
        print("swap price: ", price)
        print("swap ty: ", s.swaption_type())
        print("swap exec day:", s._expiries())
        print("Is exprired:", s.is_expired)
        print("Implied Vol: ", vol)
        assert price > 0.0
        assert vol > 0.0

    def test_atm_strike_equals_fair_rate(self, irs, cube_handle):
        s = Swaption(irs=irs, vol_surface=cube_handle)
        assert abs(s.atm_strike() - irs.vanilla().fairRate()) < 1e-12
