import pytest
from QuantLib import (
    Actual360,
    Daily,
    Date,
    DateGeneration,
    Continuous,
    FlatForward,
    ForwardCurve,
    IborIndex,
    InterestRate,
    ModifiedFollowing,
    Period,
    Schedule,
    Simple,
    TARGET,
    YieldTermStructureHandle,
    as_coupon,
    as_floating_rate_coupon,
    Preceding,
    SavedSettings,
    Settings,
    Calendar,
)
from dataclasses import FrozenInstanceError
from operator import eq, ne

from pricingengine.instruments.common import (
    CURRENCIES,
    AmortizedFixedLeg,
    AmortizedFloatingLeg,
    AmortizedSwapLeg,
    FixedLeg,
    FloatingLeg,
    SwapLeg,
    forward_marching_schedule,
    update_dates_in_schedule,
)


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
def schedule(issue_date, maturity, tenor, calendar):
    convention = ModifiedFollowing
    rule = DateGeneration.Forward
    end_of_month = False
    return Schedule(
        issue_date,
        maturity,
        tenor,
        calendar,
        convention,
        convention,
        # termination convention mirror for this fixture
        rule,
        end_of_month,
    )


@pytest.fixture
def index(calendar, day_counter, issue_date, maturity, tenor, currency):
    """Flat IborIndex for tests using a flat forward curve at 2.5%."""
    flat_rate = 0.025
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
    horizon = sch.dates()[-1] + tenor
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
    # Flat backfill for determinism
    idx.addFixings(
        tuple(idx.fixingDate(d) for d in sch.dates()),
        tuple(flat_rate for _ in sch.dates()),
        True,
    )
    return idx


# Factories — build legs under a given evaluation date
@pytest.fixture
def swap_leg(calendar, currency, day_counter, issue_date, nominal, maturity, tenor):
    def make(*, valuation_date=None):
        if valuation_date is not None:
            Settings.instance().evaluationDate = valuation_date
        return SwapLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
        )

    return make


@pytest.fixture
def fixed_leg(calendar, currency, day_counter, issue_date, nominal, maturity, tenor):
    def make(*, valuation_date=None, rate=0.0):
        if valuation_date is not None:
            Settings.instance().evaluationDate = valuation_date
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


@pytest.fixture
def floating_leg(calendar, currency, day_counter, issue_date, nominal, maturity, index, tenor):
    def make(*, valuation_date=None, gearing=1.0, spread=0.0, idx=None):
        if valuation_date is not None:
            Settings.instance().evaluationDate = valuation_date
        return FloatingLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            index=idx or index,
            gearing=gearing,
            spread=spread,
        )

    return make


@pytest.fixture
def amortized_swap():
    # Constants used across the suite
    nominal = 100_000_000.0
    currency = "SEK"
    issue_date = Date(15, 1, 2024)
    maturity = Date(15, 1, 2026)
    tenor = Period("3M")
    calendar = TARGET()
    day_counter = Actual360()

    def make(
        *,
        valuation_date: Date | None,
        amortization_period: Period,
        amortization_first_date: Date,
        amortization_last_date: Date,
        amort_amount: float | None = None,  # default 5% * nominal
    ):
        if valuation_date is not None:
            Settings.instance().evaluationDate = valuation_date

        # Build the LEG schedule exactly like SwapLeg does
        leg_schedule = Schedule(
            issue_date,
            maturity,
            tenor,
            calendar,
            ModifiedFollowing,
            Preceding,
            DateGeneration.Forward,
            False,
        )
        coupon_dates = list(leg_schedule.dates())  # FULL schedule (what SwapLeg uses)

        # Build amortization dates as a schedule too, so we get consistent BDC/EOM rolling.
        # If period or window is nonsensical, fall back to "no amortizations".
        try:
            amort_schedule = Schedule(
                amortization_first_date,
                amortization_last_date,
                amortization_period,
                calendar,
                ModifiedFollowing,  # roll like a payment date
                ModifiedFollowing,
                DateGeneration.Forward,
                False,
            )
            amort_dates = tuple(amort_schedule.dates())
        except Exception:
            amort_dates = tuple()

        step = float(nominal * 0.05) if amort_amount is None else float(amort_amount)

        # --- Core rule ---
        # For each coupon date C_i, apply every amort date A with (C_{i-1}, C_i]
        # i.e. strictly after previous coupon date and up to & including current date.
        per_coupon = []
        current = float(nominal)
        prev = None
        for ci in coupon_dates:
            if prev is None:
                # first coupon: include amortizations on/before ci but AFTER "no previous"
                # operationally: all A <= ci
                for a in amort_dates:
                    if a <= ci:
                        current = max(0.0, current - step)
            else:
                for a in amort_dates:
                    if prev < a <= ci:
                        current = max(0.0, current - step)
            per_coupon.append(current)
            prev = ci

        return AmortizedSwapLeg(
            nominal=nominal,
            currency=currency,
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=day_counter,
            per_coupon_nominals=tuple(per_coupon),
        )

    return make


# =======================
# A. Construction & validation
# =======================


class TestConstructionAndValidation:
    def test_forward_marching_schedule(self, calendar, issue_date, maturity, schedule, tenor):
        start, end, period = issue_date, maturity, tenor
        assert schedule.dates() == forward_marching_schedule(start, end, period, calendar).dates()

    def test_update_dates_in_schedule(self, schedule):
        new_dates = (
            Date(1, 2, 2024),
            Date(1, 5, 2024),
            Date(1, 8, 2024),
            Date(1, 11, 2024),
        )
        s2 = update_dates_in_schedule(schedule, new_dates)
        assert (
            s2.dates() == new_dates
            and s2.calendar() == schedule.calendar()
            and s2.businessDayConvention() == schedule.businessDayConvention()
            and s2.tenor() == schedule.tenor()
            and s2.rule() == schedule.rule()
            and s2.endOfMonth() == schedule.endOfMonth()
        )

    def test_swap_leg_construction_negative_nominal(self, calendar, currency, day_counter, issue_date, maturity, tenor):
        with pytest.raises(ValueError):
            _ = SwapLeg(
                nominal=-1.0,
                currency=currency,
                issue_date=issue_date,
                maturity=maturity,
                tenor=tenor,
                calendar=calendar,
                day_counter=day_counter,
            )

    @pytest.mark.parametrize("bad_currency", ["sek", "Swedish krona", "UZS"])
    def test_swap_leg_construction_bad_currency(self, calendar, bad_currency, day_counter, issue_date, maturity, tenor):
        with pytest.raises(ValueError):
            _ = SwapLeg(
                nominal=100_000_000,
                currency=bad_currency,
                issue_date=issue_date,
                maturity=maturity,
                tenor=tenor,
                calendar=calendar,
                day_counter=day_counter,
            )

    def test_swap_leg_immutability(self, swap_leg):
        leg = swap_leg()
        with pytest.raises(FrozenInstanceError):
            leg.tenor = Period("6M")

    def test_floating_leg_requires_nonzero_gearing(self, floating_leg):
        with pytest.raises(ValueError):
            _ = floating_leg(valuation_date=Date(15, 1, 2024), gearing=0.0)

    def test_amortized_swap_leg_never_negative(self, issue_date, maturity, tenor, calendar):
        # Build a leg whose per-coupon notionals drop to zero quickly
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
        n_future = max(0, len(sch.dates()))
        per_coupon = (0.0,) * n_future  # extreme over-amortization

        leg = AmortizedSwapLeg(
            nominal=100_000_000,
            currency="SEK",
            issue_date=issue_date,
            maturity=maturity,
            tenor=tenor,
            calendar=calendar,
            day_counter=Actual360(),
            per_coupon_nominals=per_coupon,
        )
        ns = leg.nominals
        assert all(n >= 0 for n in ns)
        assert ns[-1] == 0


# =======================
# B. Schedule invariants
# =======================


class TestScheduleInvariants:
    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_swap_leg_schedule_matches_forward(self, swap_leg, valuation_date, issue_date, maturity, tenor, calendar):
        with SavedSettings():
            Settings.instance().evaluationDate = valuation_date
            leg = swap_leg(valuation_date=valuation_date)
        expected = forward_marching_schedule(issue_date, maturity, tenor, calendar).dates()
        assert leg.schedule.dates() == expected


# =======================
# C. Future schedule behavior
# =======================


class TestFutureScheduleBehavior:
    @pytest.mark.parametrize("valuation_date, operator", [(Date(15, 1, 2024), ne), (Date(8, 7, 2024), eq)])
    def test_future_schedule_1(self, operator, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        expected = (
            Date(15, 4, 2024),
            Date(15, 7, 2024),
            Date(15, 10, 2024),
            Date(15, 1, 2025),
            Date(15, 4, 2025),
            Date(15, 7, 2025),
            Date(15, 10, 2025),
            Date(15, 1, 2026),
        )
        assert operator(expected, leg.future_schedule.dates())

    @pytest.mark.parametrize(
        "valuation_date, operator",
        [
            (Date(1, 10, 2023), eq),
            (Date(15, 1, 2024), eq),
            (Date(14, 4, 2024), eq),
            (Date(20, 4, 2024), ne),
        ],
    )
    def test_future_schedule_2(self, operator, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        assert operator(leg.schedule.dates(), leg.future_schedule.dates())

    @pytest.mark.parametrize("valuation_date", [Date(16, 1, 2024), Date(14, 4, 2024)])
    def test_future_schedule_3(self, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        fs = leg.future_schedule.dates()
        assert fs[0] < leg.valuation_date < fs[1]

    def test_future_schedule_4(self, swap_leg):
        leg = swap_leg(valuation_date=Date(8, 7, 2024))
        assert len(leg.future_schedule.dates()) < len(leg.schedule.dates())

    @pytest.mark.parametrize(
        "valuation_date",
        [Date(1, 10, 2023), Date(15, 1, 2024), Date(10, 4, 2024), Date(15, 6, 2024)],
    )
    def test_future_schedule_5(self, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        dates, fdates = set(leg.schedule.dates()), set(leg.future_schedule.dates())
        assert fdates.issubset(dates)

    @pytest.mark.parametrize("valuation_date", [Date(16, 4, 2024), Date(16, 1, 2025)])
    def test_future_schedule_6(self, swap_leg, tenor, valuation_date):
        def count(vd):
            with SavedSettings():
                Settings.instance().evaluationDate = vd
                return len(swap_leg(valuation_date=vd).future_schedule.dates())

        c1 = count(valuation_date - tenor)
        c2 = count(valuation_date)
        c3 = count(valuation_date + tenor)
        assert c3 < c2
        assert c2 < c1

    def test_future_schedule_7(self, swap_leg):
        leg = swap_leg(valuation_date=Date(8, 7, 2024))
        s, fs = leg.schedule, leg.future_schedule
        assert (
            fs.calendar()
            and fs.businessDayConvention() == s.businessDayConvention()
            and fs.tenor() == s.tenor()
            and fs.rule() == s.rule()
            and fs.endOfMonth() == s.endOfMonth()
        )


# =======================
# D. Nominals
# =======================


class TestNominals:
    def test_nominals_flat_value(self, swap_leg):
        leg = swap_leg(valuation_date=Date(8, 7, 2024))
        assert all(n == leg.nominal for n in leg.nominals)

    @pytest.mark.parametrize(
        "valuation_date",
        [Date(1, 10, 2023), Date(15, 1, 2024), Date(10, 4, 2024), Date(15, 6, 2024)],
    )
    def test_nominals_count_matches_schedule(self, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        assert len(leg.nominals) == len(leg.schedule.dates())

    def test_future_nominals_flat_value(self, swap_leg):
        leg = swap_leg(valuation_date=Date(8, 7, 2024))
        assert all(n == leg.nominal for n in leg.future_nominals)

    @pytest.mark.parametrize(
        "valuation_date",
        [Date(1, 10, 2023), Date(15, 1, 2024), Date(10, 4, 2024), Date(15, 6, 2024)],
    )
    def test_future_nominals_count_matches_future_schedule(self, swap_leg, valuation_date):
        leg = swap_leg(valuation_date=valuation_date)
        assert len(leg.future_nominals) == len(leg.future_schedule.dates())


# =======================
# E. Inheritance & structure
# =======================


class TestInheritanceAndStructure:
    def test_floating_leg_inheritance(self):
        assert issubclass(FloatingLeg, SwapLeg)

    def test_fixed_leg_inheritance(self):
        assert issubclass(FixedLeg, SwapLeg)

    def test_amortized_swap_leg_inheritance(self):
        assert issubclass(AmortizedSwapLeg, SwapLeg)

    def test_amortized_floating_leg_inheritance(self):
        assert issubclass(AmortizedFloatingLeg, (SwapLeg, FloatingLeg))

    def test_amortized_fixed_leg_inheritance(self):
        assert issubclass(AmortizedFixedLeg, (SwapLeg, FixedLeg))


# =======================
# F. Fixed/cashflow correctness
# =======================


class TestFixedCashflowCorrectness:
    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_fixed_leg_cashflows_count(self, fixed_leg, valuation_date):
        leg = fixed_leg(valuation_date=valuation_date, rate=0.02)
        assert len(leg.future_schedule.dates()) - 1 == len(leg.cashflows)

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_fixed_leg_cashflows_amounts(self, fixed_leg, valuation_date):
        leg = fixed_leg(valuation_date=valuation_date, rate=0.02)
        for i, cf in enumerate(leg.cashflows, start=1):
            c = as_coupon(cf)
            t = leg.day_counter.yearFraction(c.accrualStartDate(), c.accrualEndDate())
            assert leg.future_schedule.dates()[i] == c.accrualEndDate()
            assert pytest.approx(leg.nominal * leg.rate * t) == c.amount()

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(14, 7, 2024)])
    def test_amortized_fixed_equals_fixed_when_no_amort(self, fixed_leg, valuation_date):
        rate = 0.02
        base = fixed_leg(valuation_date=valuation_date, rate=rate)

        # Build per-coupon notionals identical to flat nominal on the FUTURE schedule
        per_coupon = tuple(base.nominal for _ in base.schedule.dates())

        leg2 = AmortizedFixedLeg(
            nominal=base.nominal,
            currency=base.currency,
            issue_date=base.issue_date,
            maturity=base.maturity,
            tenor=base.tenor,
            calendar=base.calendar,
            day_counter=base.day_counter,
            rate=rate,
            per_coupon_nominals=per_coupon,
        )
        for cf1, cf2 in zip(base.cashflows, leg2.cashflows):
            assert as_coupon(cf1).amount() == as_coupon(cf2).amount()


# =======================
# G. Amortized nominal shapes
# =======================


class TestAmortizedNominalShapes:
    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_schedule_invariant(self, amortized_swap, issue_date, maturity, tenor, valuation_date):
        leg1 = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=tenor,
            amortization_first_date=issue_date,
            amortization_last_date=maturity,
        )
        leg2 = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=2 * tenor,
            amortization_first_date=issue_date + Period("2W"),
            amortization_last_date=maturity,
        )
        expected = (
            Date(15, 1, 2024),
            Date(15, 4, 2024),
            Date(15, 7, 2024),
            Date(15, 10, 2024),
            Date(15, 1, 2025),
            Date(15, 4, 2025),
            Date(15, 7, 2025),
            Date(15, 10, 2025),
            Date(15, 1, 2026),
        )
        assert leg1.schedule.dates() == expected == leg2.schedule.dates()

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_nominals_same_as_schedule(self, amortized_swap, issue_date, maturity, tenor, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=tenor,
            amortization_first_date=issue_date,
            amortization_last_date=maturity,
        )
        expected = (
            95_000_000.0,
            90_000_000.0,
            85_000_000.0,
            80_000_000.0,
            75_000_000.0,
            70_000_000.0,
            65_000_000.0,
            60_000_000.0,
            55_000_000.0,
        )
        assert leg.nominals == expected

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_nominals_count(self, amortized_swap, issue_date, maturity, tenor, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=tenor,
            amortization_first_date=issue_date,
            amortization_last_date=maturity,
        )
        assert len(leg.nominals) == len(leg.schedule.dates())

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_amort_starts_later(self, amortized_swap, issue_date, maturity, tenor, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=tenor,
            amortization_first_date=issue_date + Period("6M"),
            amortization_last_date=maturity,
        )
        expected = (
            100_000_000,
            100_000_000,
            95_000_000,
            90_000_000,
            85_000_000,
            80_000_000,
            75_000_000,
            70_000_000,
            65_000_000,
        )
        assert leg.nominals == expected

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_amort_starts_later_ends_before(self, amortized_swap, issue_date, maturity, tenor, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=tenor,
            amortization_first_date=issue_date + Period("6M"),
            amortization_last_date=maturity - Period("3M"),
        )
        expected = (
            100_000_000,
            100_000_000,
            95_000_000,
            90_000_000,
            85_000_000,
            80_000_000,
            75_000_000,
            70_000_000,
            70_000_000,  # flat after last amortization
        )
        assert leg.nominals == expected

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_amort_every_6m(self, amortized_swap, issue_date, maturity, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=Period("6M"),
            amortization_first_date=issue_date,
            amortization_last_date=maturity,
        )
        expected = (
            95_000_000,
            95_000_000,
            90_000_000,
            90_000_000,
            85_000_000,
            85_000_000,
            80_000_000,
            80_000_000,
            75_000_000,
        )
        assert leg.nominals == expected

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(30, 4, 2024)])
    def test_amort_every_2m_inside_window(self, amortized_swap, issue_date, maturity, valuation_date):
        leg = amortized_swap(
            valuation_date=valuation_date,
            amortization_period=Period("2M"),
            amortization_first_date=issue_date + Period("2M"),
            amortization_last_date=maturity - Period("2M"),
        )
        expected = (
            100_000_000.0,
            95_000_000.0,
            85_000_000.0,
            80_000_000.0,
            70_000_000.0,
            65_000_000.0,
            55_000_000.0,
            50_000_000.0,
            45_000_000.0,
        )
        assert leg.nominals == expected


# =======================
# H. Fixed vs Floating equivalences
# =======================


class TestFixedVsFloatingEquivalence:
    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(14, 7, 2024)])
    def test_equal_2pct_flat(self, fixed_leg, floating_leg, valuation_date):
        """Fixed 2% vs Floating with flat Libor 2%, no spread/gearing."""
        simple_rate, gearing, spread = 0.02, 1, 0.00
        leg_fixed = fixed_leg(valuation_date=valuation_date, rate=simple_rate)

        continuous_rate = (
            InterestRate(simple_rate, Actual360(), Simple, Daily)
            .equivalentRate(Actual360(), Continuous, Daily, Date(15, 1, 2024), Date(15, 4, 2024))
            .rate()
        )
        flat_forward = FlatForward(valuation_date, continuous_rate, Actual360(), Continuous, Daily)

        forecast_index = IborIndex(
            "Libor",
            leg_fixed.tenor,
            2,
            CURRENCIES[leg_fixed.currency],
            leg_fixed.calendar,
            ModifiedFollowing,
            False,
            leg_fixed.day_counter,
            YieldTermStructureHandle(flat_forward),
        )
        leg_float = floating_leg(
            valuation_date=valuation_date,
            gearing=gearing,
            spread=spread,
            idx=forecast_index,
        )

        forecast_index.addFixings(
            tuple(forecast_index.fixingDate(d) for d in leg_float.schedule.dates()),
            tuple(simple_rate for _ in leg_float.schedule.dates()),
            forceOverwrite=True,
        )

        for cf1, cf2 in zip(leg_fixed.cashflows, leg_float.cashflows):
            c1, c2 = as_coupon(cf1), as_floating_rate_coupon(cf2)
            assert c1.accrualStartDate() == c2.accrualStartDate()
            assert c1.accrualEndDate() == c2.accrualEndDate()
            assert c1.nominal() == c2.nominal()
            assert pytest.approx(c1.rate(), rel=1e-4) == pytest.approx(c2.rate(), rel=1e-4)
            assert pytest.approx(c1.amount(), rel=1e-4) == pytest.approx(c2.amount(), rel=1e-4)
        forecast_index.clearFixings()

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(14, 7, 2024)])
    def test_equal_2pct_with_1pct_spread(self, fixed_leg, floating_leg, valuation_date):
        """Fixed 2% vs Floating flat Libor 1% + 1% spread."""
        simple_rate, gearing, spread = 0.02, 1, 0.01
        leg_fixed = fixed_leg(valuation_date=valuation_date, rate=simple_rate)

        continuous_rate = (
            InterestRate(simple_rate, Actual360(), Simple, Daily)
            .equivalentRate(Actual360(), Continuous, Daily, Date(15, 1, 2024), Date(15, 4, 2024))
            .rate()
        )
        flat_forward = FlatForward(valuation_date, continuous_rate - spread, Actual360(), Continuous, Daily)

        forecast_index = IborIndex(
            "Libor",
            leg_fixed.tenor,
            2,
            CURRENCIES[leg_fixed.currency],
            leg_fixed.calendar,
            ModifiedFollowing,
            False,
            leg_fixed.day_counter,
            YieldTermStructureHandle(flat_forward),
        )
        leg_float = floating_leg(
            valuation_date=valuation_date,
            gearing=gearing,
            spread=spread,
            idx=forecast_index,
        )

        forecast_index.addFixings(
            tuple(forecast_index.fixingDate(d) for d in leg_float.schedule.dates()),
            tuple(simple_rate - spread for _ in leg_float.schedule.dates()),
            forceOverwrite=True,
        )

        for cf1, cf2 in zip(leg_fixed.cashflows, leg_float.cashflows):
            c1, c2 = as_coupon(cf1), as_floating_rate_coupon(cf2)
            assert c1.accrualStartDate() == c2.accrualStartDate()
            assert c1.accrualEndDate() == c2.accrualEndDate()
            assert c1.nominal() == c2.nominal()
            assert pytest.approx(c1.rate(), rel=1e-2) == pytest.approx(c2.rate(), rel=1e-2)
            assert pytest.approx(c1.amount(), rel=1e-2) == pytest.approx(c2.amount(), rel=1e-2)
        forecast_index.clearFixings()

    @pytest.mark.parametrize("valuation_date", [Date(1, 10, 2023), Date(15, 1, 2024), Date(14, 7, 2024)])
    def test_equal_gearing2(self, fixed_leg, floating_leg, valuation_date):
        """Fixed 2% vs Floating flat Libor 1% with 2x gearing."""
        rate, gearing, spread = 0.02, 2, 0.00
        leg_fixed = fixed_leg(valuation_date=valuation_date, rate=rate)

        flat_forward = ForwardCurve(
            (valuation_date, leg_fixed.schedule.dates()[-1]),
            (rate / gearing, rate / gearing),
            leg_fixed.day_counter,
        )
        forecast_index = IborIndex(
            "Libor",
            leg_fixed.tenor,
            2,
            CURRENCIES[leg_fixed.currency],
            leg_fixed.calendar,
            ModifiedFollowing,
            False,
            leg_fixed.day_counter,
            YieldTermStructureHandle(flat_forward),
        )
        leg_float = floating_leg(
            valuation_date=valuation_date,
            gearing=gearing,
            spread=spread,
            idx=forecast_index,
        )

        forecast_index.addFixings(
            tuple(forecast_index.fixingDate(d) for d in leg_float.schedule.dates()),
            tuple(rate / gearing for _ in leg_float.schedule.dates()),
            forceOverwrite=True,
        )

        for cf1, cf2 in zip(leg_fixed.cashflows, leg_float.cashflows):
            c1, c2 = as_coupon(cf1), as_floating_rate_coupon(cf2)
            assert c1.accrualStartDate() == c2.accrualStartDate()
            assert c1.accrualEndDate() == c2.accrualEndDate()
            assert c1.nominal() == c2.nominal()
            assert pytest.approx(c1.rate(), rel=1e-2) == pytest.approx(c2.rate(), rel=1e-2)
            assert pytest.approx(c1.amount(), rel=1e-2) == pytest.approx(c2.amount(), rel=1e-2)
        forecast_index.clearFixings()
