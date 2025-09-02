"""Swap leg building utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from QuantLib import (
    CashFlow,
    Date,
    DayCounter,
    FixedRateLeg,
    IborLeg,
    Index,
    Schedule,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class SwapLeg(ABC):
    """Common fields for swap legs."""

    valuation_date: Date
    issue_date: Date
    maturity: Date
    currency: str
    day_counter: DayCounter
    future_schedule: Schedule
    nominal: float

    @abstractmethod
    def cashflows(self, *, forecast_index: Index | None = None) -> list[CashFlow]:
        """Return QuantLib cashflows for this leg."""


@dataclass(frozen=True, kw_only=True, slots=True)
class FixedLeg(SwapLeg):
    """Fixed-rate leg."""

    rate: float

    def cashflows(self, *, forecast_index: Index | None = None) -> list[CashFlow]:
        leg = FixedRateLeg(
            self.future_schedule,
            self.day_counter,
            [self.nominal],
            [self.rate],
        )
        return list(leg)


@dataclass(frozen=True, kw_only=True, slots=True)
class FloatingLeg(SwapLeg):
    """Floating-rate leg referencing an Ibor-like index."""

    spread: float = 0.0

    def cashflows(self, *, forecast_index: Index | None = None) -> list[CashFlow]:
        if forecast_index is None:
            raise ValueError("forecast_index required for floating leg cashflows")
        leg = IborLeg(
            [self.nominal],
            self.future_schedule,
            forecast_index,
            paymentDayCounter=self.day_counter,
            spreads=[self.spread],
        )
        return list(leg)


__all__ = ["SwapLeg", "FixedLeg", "FloatingLeg"]
