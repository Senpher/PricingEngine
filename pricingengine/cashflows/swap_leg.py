from __future__ import annotations

from dataclasses import dataclass

from QuantLib import (
    Date,
    DayCounter,
    FixedRateLeg,
    IborLeg,
)


@dataclass(frozen=True, kw_only=True, slots=True)

    valuation_date: Date
    issue_date: Date
    maturity: Date
    currency: str
    future_schedule: Schedule



@dataclass(frozen=True, kw_only=True, slots=True)
class FixedLeg(SwapLeg):

    rate: float

            self.future_schedule,
            self.day_counter,
            [self.nominal],
            [self.rate],
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class FloatingLeg(SwapLeg):

    spread: float = 0.0

        if forecast_index is None:
            [self.nominal],
            self.future_schedule,
            forecast_index,
            spreads=[self.spread],
        )
