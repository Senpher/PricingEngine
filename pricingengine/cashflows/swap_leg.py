from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from typing import cast

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
    as_coupon,
    as_floating_rate_coupon,
)
from pandas import DataFrame, option_context

from pricingengine.currencies import CURRENCIES

# Standard schedule construction parameters used across legs
_CONVENTION = ModifiedFollowing
_TERMINATION_CONVENTION = Preceding
_RULE = DateGeneration.Forward
_END_OF_MONTH = False


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

    @cached_property
    def schedule(self) -> Schedule:
        """Returns a schedule with all payment dates according to swap-leg settings."""
        return Schedule(
            self.issue_date,
            self.maturity,
            self.tenor,
            self.calendar,
            _CONVENTION,
            _TERMINATION_CONVENTION,
            _RULE,
            _END_OF_MONTH,
        )

    @cached_property
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
        cutoff = self.valuation_date - self.tenor
        dates = [d for d in self.schedule.dates() if d > cutoff]
        return Schedule(
            dates,
            self.calendar,
            _CONVENTION,
            _CONVENTION,
            self.tenor,
            _RULE,
            _END_OF_MONTH,
        )

    @property
    def nominals(self) -> tuple[float, ...]:
        """Returns fixed nominal value of the swap-leg for all payment dates."""
        return tuple(self.nominal for _ in self.schedule.dates())

    @property
    def future_nominals(self) -> tuple[float, ...]:
        """Returns a nominal values for future payments."""
        cutoff_sn = (self.valuation_date - self.tenor).serialNumber()
        return tuple(
            n
            for n, d in zip(self.nominals, self.schedule.dates())
            if d.serialNumber() > cutoff_sn
        )


@dataclass(frozen=True, kw_only=True)
class FloatingLeg(SwapLeg):
    """Class that represents a floating leg in a swap contract with fixed nominal."""

    index: IborIndex
    gearing: float
    spread: float

    def __post_init__(self):
        super().__post_init__()
        # Minimal sanity checks (don’t enforce tenor equality too aggressively—
        # users may want stubs)
        if self.gearing == 0.0:
            raise ValueError("gearing must be non-zero for floating leg")

    # To use to create a new leg with new index
    # DO NOT MODIFY INDEX ATTRIBUTE AFTER CREATION
    # Else cached cashflows won't be bound to the updated index if you do
    def with_index(self, index: IborIndex) -> FloatingLeg:
        return replace(self, index=index)

    @cached_property
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
            return cast(tuple[CashFlow, ...], tuple())
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
class FixedLeg(SwapLeg):
    """Class that represents a fixed leg in a swap contract with fixed nominal."""

    rate: float

    @cached_property
    def cashflows(self) -> tuple[CashFlow]:
        """Returns future cash flow payments for fixed interest rate."""
        sch = self.future_schedule
        n = len(sch.dates()) - 1
        if n <= 0:
            return cast(tuple[CashFlow, ...], tuple())
        rates = (self.rate,) * n
        # first 4 argument are only exposed positionally
        return FixedRateLeg(
            sch,
            self.day_counter,
            self.future_nominals[:-1],
            rates,
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
        return Schedule(
            self.amortization_first_date,
            self.amortization_last_date,
            self.amortization_period,
            self.calendar,
            _CONVENTION,
            _TERMINATION_CONVENTION,
            _RULE,
            _END_OF_MONTH,
        )

    @property
    def nominals(self) -> tuple[float, ...]:
        """Returns amortized nominal values of the swap-leg for all payment dates."""
        ns: list[float] = []
        for date in self.schedule.dates():
            amortized = sum(
                self.amortization_amount
                for amortization_date in self.amortization_schedule.dates()
                if amortization_date <= date
            )
            n = max(0.0, float(self.nominal) - float(amortized))
            ns.append(n)
        return tuple(ns)


@dataclass(frozen=True, kw_only=True)
class AmortizedFloatingLeg(FloatingLeg, AmortizedSwapLeg):
    """Floating leg in a swap contract with amortized nominal."""

    pass


@dataclass(frozen=True, kw_only=True)
class AmortizedFixedLeg(FixedLeg, AmortizedSwapLeg):
    """Fixed leg in a swap contract with amortized nominal."""

    pass
