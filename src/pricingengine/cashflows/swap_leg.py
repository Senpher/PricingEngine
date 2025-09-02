from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from QuantLib import (
    Date,
    Schedule,
    DayCounter,
    Index,
    Leg,
    FixedRateLeg,
    IborLeg,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class SwapLeg:
    """Base class for swap legs."""

    valuation_date: Date
    issue_date: Date
    maturity: Date
    currency: str
    nominal: float
    future_schedule: Schedule
    day_counter: DayCounter

    def cashflows(self, forecast_index: Optional[Index] = None) -> Leg:
        """Return QuantLib leg cashflows."""
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True, slots=True)
class FixedLeg(SwapLeg):
    """Fixed coupon leg."""

    rate: float

    def cashflows(self, forecast_index: Optional[Index] = None) -> Leg:  # type: ignore[override]
        return FixedRateLeg(
            self.future_schedule,
            self.day_counter,
            [self.nominal],
            [self.rate],
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class FloatingLeg(SwapLeg):
    """Floating-rate leg indexed to an Ibor-like index."""

    spread: float = 0.0

    def cashflows(self, forecast_index: Optional[Index] = None) -> Leg:  # type: ignore[override]
        if forecast_index is None:
            raise ValueError("forecast_index is required for floating leg cashflows")
        return IborLeg(
            [self.nominal],
            self.future_schedule,
            forecast_index,
            self.day_counter,
            spreads=[self.spread],
        )
