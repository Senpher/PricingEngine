from __future__ import annotations

from typing import Optional
from QuantLib import (
    Calendar,
    CashFlow,
    DateGeneration,
    Date,
    DayCounter,
    FixedRateLeg,
    IborLeg,
    Index,
    ModifiedFollowing,
    Period,
    Preceding,
    Schedule,
    as_coupon,
    as_floating_rate_coupon,
)
from dataclasses import dataclass, replace
from pandas import DataFrame, option_context

from pricingengine.currencies import CURRENCIES


def forward_marching_schedule(
        start: Date, end: Date, period: Period, calendar: Calendar
) -> Schedule:
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

    valuation_date: Date
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
            raise ValueError(
                "'currency' is not supported in QuantLib - unable to create index"
            )

    @property
    def schedule(self) -> Schedule:
        """Returns a schedule with all payment dates according to swap-leg settings."""
        return forward_marching_schedule(
            start=self.issue_date,
            end=self.maturity,
            period=self.tenor,
            calendar=self.calendar,
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
        corrected_start = self.valuation_date - self.tenor
        dates = tuple(date for date in self.schedule.dates() if date > corrected_start)
        return update_dates_in_schedule(self.schedule, dates)

    @property
    def nominals(self) -> tuple[float, ...]:
        """Returns fixed nominal value of the swap-leg for all payment dates."""
        return tuple(self.nominal for _ in self.schedule.dates())

    @property
    def future_nominals(self) -> tuple[float, ...]:
        """Returns a nominal values for future payments."""
        corrected_start = self.valuation_date - self.tenor
        return tuple(
            nominal for nominal, date in zip(self.nominals, self.schedule.dates()) if date > corrected_start
        )


@dataclass(frozen=True, kw_only=True)
class FloatingLeg(SwapLeg):
    """Class that represents a floating leg in a swap contract with fixed nominal."""

    index: Optional[Index] = None
    gearing: float
    spread: float

    def with_index(self, index: Index) -> FloatingLeg:
        return replace(self, index=index)

    def cashflows(self, forecast_index: Optional[Index] = None) -> tuple[CashFlow]:
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
        idx = forecast_index or self.index
        if idx is None:
            raise ValueError("FloatingLeg needs an Index (pass forecast_index=... or set leg.index)")

        return IborLeg(
            nominals=self.future_nominals[:-1],
            schedule=self.future_schedule,
            index=idx,
            paymentDayCounter=self.day_counter,
            paymentConvention=ModifiedFollowing,
            gearings=tuple(self.gearing for _ in self.future_schedule.dates()[:-1]),
            spreads=tuple(self.spread for _ in self.future_schedule.dates()[:-1]),
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
class FixedLeg(SwapLeg):
    """Class that represents a fixed leg in a swap contract with fixed nominal."""

    rate: float

    def cashflows(self) -> tuple[CashFlow]:
        """Returns future cash flow payments for fixed interest rate."""
        fixed_rates = tuple(self.rate for _ in self.future_schedule.dates())
        return FixedRateLeg(
            self.future_schedule,  # first 4 argument are only exposed positionally
            self.day_counter,
            self.future_nominals[:-1],
            fixed_rates
        )

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

    amortization_amount: float
    amortization_period: Period
    amortization_first_date: Date
    amortization_last_date: Date

    def __post_init__(self):
        super().__post_init__()
        if not all(nominal >= 0 for nominal in self.nominals):
            raise ValueError(
                "Amortized swap leg cannot produce negative cashflow nominals."
            )

    @property
    def amortization_schedule(self) -> Schedule:
        """
        Returns a schedule with all amortization dates according to the
        swap-leg settings.
        """
        return forward_marching_schedule(
            start=self.amortization_first_date,
            end=self.amortization_last_date,
            period=self.amortization_period,
            calendar=self.calendar,
        )

    @property
    def nominals(self) -> tuple[float]:
        """Returns amortized nominal values of the swap-leg for all payment dates."""
        ns = ()
        for date in self.schedule.dates():
            amortized = sum(
                self.amortization_amount
                for amortization_date in self.amortization_schedule.dates()
                if amortization_date <= date
            )
            n = max(0.0, float(self.nominal) - float(amortized))
            ns += (n,)
        return ns


@dataclass(frozen=True, kw_only=True)
class AmortizedFloatingLeg(FloatingLeg, AmortizedSwapLeg):
    """Class that represents a floating leg in a swap contract with amortized nominal."""

    pass


@dataclass(frozen=True, kw_only=True)
class AmortizedFixedLeg(FixedLeg, AmortizedSwapLeg):
    """Class that represents a fixed leg in a swap contract with amortized nominal."""

    pass
