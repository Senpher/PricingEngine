from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from QuantLib import (
    Date,
    DayCounter,
    FixedRateLeg,
    IborLeg,
    Index,
    Schedule,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class SwapLeg(ABC):
    """Base class for a swap leg.

    Holds the minimal information shared by fixed and floating legs and
    exposes an abstract :meth:`cashflows` method that returns a QuantLib
    ``Leg`` ready to be attached to a swap.
    """

    valuation_date: Date
    issue_date: Date
    maturity: Date
    currency: str
    day_counter: DayCounter
    future_schedule: Schedule
    nominal: float

    def is_expired(self) -> bool:
        return self.valuation_date >= self.maturity

    @abstractmethod
    def cashflows(
        self, *, forecast_index: Index | None = None, **kwargs
    ):  # pragma: no cover - thin wrapper
        """Return the QuantLib cashflows for the leg."""
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True, slots=True)
class FixedLeg(SwapLeg):
    rate: float

    def cashflows(
        self, *, forecast_index: Index | None = None, **kwargs
    ):  # noqa: ARG002 - unused
        return FixedRateLeg(
            self.future_schedule,
            self.day_counter,
            [self.nominal],
            [self.rate],
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class FloatingLeg(SwapLeg):
    spread: float = 0.0

    def cashflows(
        self, *, forecast_index: Index | None = None, **kwargs
    ):  # noqa: ARG002 - kwargs unused
        if forecast_index is None:
            raise ValueError("forecast_index is required for floating leg cashflows")
        return IborLeg(
            [self.nominal],
            self.future_schedule,
            forecast_index,
            spreads=[self.spread],
            paymentDayCounter=self.day_counter,
        )
