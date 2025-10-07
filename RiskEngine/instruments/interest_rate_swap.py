from __future__ import annotations

from dataclasses import dataclass

from QuantLib import Date, Settings, YieldTermStructureHandle

from .base import MarketLinkedInstrument


@dataclass(frozen=True)
class InterestRateSwapInstrument(MarketLinkedInstrument):
    """Plain-vanilla fixed-for-floating interest rate swap."""

    currency: str
    discount_curve: YieldTermStructureHandle
    payment_dates: tuple[Date, ...]
    fixed_rate: float
    notional: float
    spread: float = 0.0

    def __post_init__(self) -> None:
        if not self.payment_dates:
            raise ValueError("payment_dates must contain at least one date")
        if self.notional <= 0:
            raise ValueError("notional must be positive")

    def npv(self) -> float:
        dc = self.discount_curve.dayCounter()
        eval_date = Settings.instance().evaluationDate
        previous = eval_date
        pv_fixed = 0.0
        pv_float = 0.0
        prev_df = self.discount_curve.discount(previous)
        for payment_date in self.payment_dates:
            accrual = dc.yearFraction(previous, payment_date)
            df = self.discount_curve.discount(payment_date)
            pv_fixed += df * accrual * self.fixed_rate * self.notional
            forward_rate = (prev_df / df - 1.0) / accrual if accrual > 0 else 0.0
            pv_float += df * accrual * (forward_rate + self.spread) * self.notional
            previous = payment_date
            prev_df = df
        return pv_float - pv_fixed
