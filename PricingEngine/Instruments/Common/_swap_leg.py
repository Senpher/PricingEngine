from __future__ import annotations

from dataclasses import dataclass, replace

from pandas import DataFrame, option_context
from QuantLib import (
    Calendar,
    CashFlow,
    Date,
    DateGeneration,
    DayCounter,
    FixedRateLeg,
    IborIndex,
    IborLeg,
    ModifiedFollowing,
    Period,
    Preceding,
    Schedule,
    Settings,
    as_coupon,
    as_floating_rate_coupon,
)

from PricingEngine.Instruments.Common import CURRENCIES


def forward_marching_schedule(start: Date, end: Date, period: Period, calendar: Calendar) -> Schedule:
    """
    Returns a forward marching schedule.

    Dates in the schedule are gives as

              D1    D2    D3        DL
    start ... | ... | ... | ... ... | ... end

    where dates D1, D2, D3 through DL are located on `period` distance from
    each other.

    Notable function behaviour:

    - when `end` - `start` <= `period` there are only two dates in the
      schedule

    - when (`end` - `start`) / `period` is not divisible in which case `end` -
      DL is smaller than `period` (i.e., schedule is not equidistant)

    - when a payment date coincides with a holiday in the calendar the payment
      date is moved on the following business date
    """
    CONVENTION = ModifiedFollowing
    TERMINATION_CONVENTION = Preceding
    RULE = DateGeneration.Forward
    END_OF_MONTH = False
    return Schedule(
        start,
        end,
        period,
        calendar,
        CONVENTION,
        TERMINATION_CONVENTION,
        RULE,
        END_OF_MONTH,
    )


def update_dates_in_schedule(schedule: Schedule, new_dates: tuple[Date, ...]) -> Schedule:
    """
    Returns a schedule with `new_dates` and the remaining schedule parameters
    templated from `schedule`.
    """
    return Schedule(
        new_dates,
        schedule.calendar(),
        schedule.businessDayConvention(),
        schedule.businessDayConvention(),
        schedule.tenor(),
        schedule.rule(),
        schedule.endOfMonth(),
    )


@dataclass(frozen=True, kw_only=True)
class SwapLeg:
    """
    Base class representing a swap-leg with fixed nominal payment schedule.

    The class represents the following structure

                         D1    D2    D3        DL
      ... issue_date ... | ... | ... | ... ... | ... maturity
       ^                 P1    P2    P3        PL
       valuation_date

    where D1, D2, D3 through DL are dates and P1, P2, P3 through PL are
    respective future payments for those dates. `valuation_date` is a point at
    which the future payments are priced. `valuation_date` can also be after
    the `issue_date`.

    The base class holds information about payment dates, according to the
    payment schedule, and respective nominal values for interest-rate payments.
    This information is used to calculate the size and the date of the payments
    using QuantLib.
    """

    nominal: float
    currency: str
    issue_date: Date
    maturity: Date
    tenor: Period
    calendar: Calendar
    day_counter: DayCounter

    def __post_init__(self):
        if self.nominal < 0:
            raise ValueError("'nominal' must be positive")

        if self.currency not in CURRENCIES:
            raise ValueError("'currency' is not supported in QuantLib - unable to create index")

    @property
    def valuation_date(self) -> Date:
        # Always reflect the current global eval date
        return Settings.instance().evaluationDate

    @property
    def schedule(self) -> Schedule:
        """Returns a schedule with all payment dates according to swap-leg settings."""
        return Schedule(
            self.issue_date,
            self.maturity,
            self.tenor,
            self.calendar,
            ModifiedFollowing,
            Preceding,
            DateGeneration.Forward,
            False,
        )

    @property
    def future_schedule(self) -> Schedule:
        """
        Returns a schedule with dates for future payments.

        Dates in the future schedule are a subset of all payment dates and
        depend on `valuation_date` as follows

        - `valuation_date` >= `issue_date` + `tenor`

                             D1    D2    D3        DL
          ... issue_date ... | ... | ... | ... ... | ... maturity
                                   F1 ^  F2        FL-1
                                      valuation_date

        - `valuation_date` < `issue_date` + `tenor`

                             D1    D2    D3        DL
          ... issue_date ... | ... | ... | ... ... | ... maturity
           ^                 F1    F2    F3        FL
           valuation_date

        where F1, F2, F3 through FL/FL-1 are dates in the future schedule. In
        the former example, `future_schedule` is shorter than `schedule` and in
        the latter `future_schedule` is the same length as `schedule`.
        """
        sch = self.schedule  # capture once; don't recreate repeatedly
        cutoff = self.valuation_date - self.tenor

        dates_all = list(sch.dates())
        dates = [d for d in dates_all if d > cutoff]

        # QuantLib needs at least two dates for a valid schedule.
        # If filtering got us < 2 dates, keep the last two original dates.
        if len(dates) < 2:
            if len(dates_all) >= 2:
                dates = dates_all[-2:]
            else:
                # extremely defensive: fall back to whatever we have
                dates = dates_all

        return Schedule(
            dates,
            sch.calendar(),
            sch.businessDayConvention(),
            sch.businessDayConvention(),
            self.tenor,  # <- use the leg's original tenor, not sch.tenor()
            sch.rule(),
            sch.endOfMonth(),
        )

    @property
    def nominals(self) -> tuple[float, ...]:
        """Returns fixed nominal value of the swap-leg for all payment dates."""
        return tuple(self.nominal for _ in self.schedule.dates())

    @property
    def future_nominals(self) -> tuple[float, ...]:
        """Returns a nominal values for future payments."""
        dates = self.future_schedule.dates()
        return tuple(self.nominal for _ in dates)


@dataclass(frozen=True, kw_only=True)
class FixedLeg(SwapLeg):
    """Class that represents a fixed leg in a swap contract with fixed nominal."""

    rate: float

    @property
    def cashflows(self) -> tuple[CashFlow]:
        """Returns future cash flow payments for fixed interest rate."""
        sch = self.future_schedule
        n = len(sch.dates()) - 1
        if n <= 0:
            return tuple()
        rates = (self.rate,) * n
        # first 4 argument are only exposed positionally
        return FixedRateLeg(sch, self.day_counter, self.future_nominals[:-1], rates)

    @staticmethod
    def debug(cashflows: tuple[CashFlow]) -> None:
        """Display detailed information about provided cash flows."""
        coupons = tuple(as_coupon(cf) for cf in cashflows)

        df = (
            DataFrame(
                data=(
                    {
                        "Date": c.date().ISO(),
                        "Nominal": c.nominal(),
                        "AccrualStartDate": c.accrualStartDate().ISO(),
                        "AccrualEndDate": c.accrualEndDate().ISO(),
                        "AccrualDays": c.accrualDays(),
                        "Rate": c.rate(),
                    }
                    for c in coupons
                )
            )
            .round({"Nominal": 2, "Rate": 5})
            .set_index("Date")
        )
        with option_context("display.float_format", "{:,.2f}".format):
            df["Rate"] = df.Rate.map("{:,.6f}".format)
            print(df)


@dataclass(frozen=True, kw_only=True)
class FloatingLeg(SwapLeg):
    """Class that represents a floating leg in a swap contract with fixed nominal."""

    index: IborIndex
    gearing: float
    spread: float

    def __post_init__(self):
        super().__post_init__()
        # Minimal sanity checks (don’t enforce tenor equality too aggressively—users may want stubs)
        if self.gearing == 0.0:
            raise ValueError("gearing must be non-zero for floating leg")

    def with_index(self, index: IborIndex) -> FloatingLeg:
        return replace(self, index=index)

    @property
    def cashflows(self) -> tuple[CashFlow]:
        """
        Returns future cash flow payments for variable interest rate.

        `forecast_index` represents a time series containing of forward rates
        associated with a reference interest-rate swap index, such as Libor or
        OIS, with a tenor matching that of the swap's floating leg. Forward
        rates are either implied from a yield curve for future dates or
        realized fixings for past market interest rates.

        Libor-like indices have a settlement period of two days. This means
        that forward rates in `forecast_index` are applied on cash flows on T +
        index settlement period. OIS indices settle on the same day.
        """
        sch = self.future_schedule
        dates = sch.dates()
        n = len(dates) - 1
        if n <= 0:
            return tuple()
        return IborLeg(
            nominals=self.future_nominals[:-1],
            schedule=sch,
            index=self.index,
            paymentDayCounter=self.day_counter,
            paymentConvention=ModifiedFollowing,
            gearings=(self.gearing,) * n,
            spreads=(self.spread,) * n,
        )

    @staticmethod
    def debug(cashflows: tuple[CashFlow]) -> None:
        """Display detailed information about provided cash flows."""
        coupons = tuple(as_floating_rate_coupon(cf) for cf in cashflows)

        df = (
            DataFrame(
                data=(
                    {
                        "Date": c.date().ISO(),
                        "Nominal": c.nominal(),
                        "Gearing": c.gearing(),
                        "Spread": c.spread(),
                        "AccrualStartDate": c.accrualStartDate().ISO(),
                        "AccrualEndDate": c.accrualEndDate().ISO(),
                        "AccrualDays": c.accrualDays(),
                        "FixingDate": c.fixingDate().ISO(),
                        "Rate": c.indexFixing(),
                    }
                    for c in coupons
                )
            )
            .round({"Nominal": 2, "Rate": 5, "Gearing": 2, "Spread": 5})
            .set_index("Date")
        )
        with option_context("display.float_format", "{:,.2f}".format):
            df["Spread"] = df.Spread.map("{:,.6f}".format)
            df["Rate"] = df.Rate.map("{:,.6f}".format)
            print(df)


@dataclass(frozen=True, kw_only=True)
class AmortizedSwapLeg(SwapLeg):
    """
    Base class representing a swap-leg with amortized nominal payment schedule.

    The class extends `SwapLeg` where the initial nominal of the swap is
    amortized according to an amortization schedule

                         D1    D2    D3        DL
      ... issue_date ... | ... | ... | ... ... | ... maturity
       ^                 N  ^  N-A   N-2*A     N-K*A     ^
       |                    |                            |
       valuation_date       amortization_first_date      amortization_last_date

    where D1, D2, D3 through DL are dates and N is the initial nominal
    amortized with `amortization_amount` A in each `amortization_period`.
    """

    per_coupon_nominals: tuple[float, ...]

    def __post_init__(self):
        # If SwapLeg defines its own __post_init__, let it run first.
        super_post = getattr(super(), "__post_init__", None)
        if callable(super_post):
            super_post()

        # Enforce full-schedule vector (match the base SwapLeg convention).
        n_sch = len(self.schedule.dates())
        if len(self.per_coupon_nominals) != n_sch:
            raise ValueError(
                f"per_coupon_nominals length ({len(self.per_coupon_nominals)}) must equal "
                f"the schedule length used by SwapLeg ({n_sch})."
            )
        if any(x < 0 for x in self.per_coupon_nominals):
            raise ValueError("per_coupon_nominals must be non-negative.")

    # ---- overrides ----
    @property
    def nominals(self) -> tuple[float, ...]:
        """Return nominal per *each schedule date* (full-schedule, as in base SwapLeg)."""
        return tuple(self.per_coupon_nominals)

    @property
    def future_nominals(self) -> tuple[float, ...]:
        """
        Return nominal values for *future* payments.
        We assume future_schedule is a suffix of schedule -> take the last N entries.
        """
        full_dates = list(self.schedule.dates())
        fut_dates = self.future_schedule.dates()
        idx = [full_dates.index(d) for d in fut_dates]
        return tuple(self.per_coupon_nominals[i] for i in idx)


@dataclass(frozen=True, kw_only=True)
class AmortizedFixedLeg(AmortizedSwapLeg, FixedLeg):
    """Fixed leg with amortizing notionals (explicit per-coupon vector)."""

    pass


@dataclass(frozen=True, kw_only=True)
class AmortizedFloatingLeg(AmortizedSwapLeg, FloatingLeg):
    """Floating leg with amortizing notionals (explicit per-coupon vector)."""

    pass
