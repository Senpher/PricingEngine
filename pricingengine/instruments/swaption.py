from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from QuantLib import (
    BachelierSwaptionEngine,
    BermudanExercise,
    BlackSwaptionEngine,
    Date,
    EuropeanExercise,
    QuoteHandle,
    Settlement,
    SimpleQuote,
    VanillaSwap,
)
from QuantLib import Swaption as QLSwaption

from pricingengine.instruments._instrument import Instrument
from pricingengine.instruments.interest_rate_swap import InterestRateSwap


@dataclass(frozen=True, kw_only=True, slots=True)
class Swaption(Instrument):
    """Vanilla swaption on a single-currency :class:`InterestRateSwap`."""

    swap: InterestRateSwap
    expiries: Optional[Sequence[Date]] = None
    strike: Optional[float] = None
    volatility: float = 0.01
    vol_type: str = "black"  # "black" or "normal"
    settlement: str = "physical"  # "physical" or "cash"
    is_long: bool = True

    # ------------------------------------------------------------------
    # convenience properties
    @property
    def valuation_date(self) -> Date:
        return self.swap.valuation_date

    @property
    def currency(self):
        return self.swap.currency

    @property
    def is_european(self) -> bool:
        return len(self._expiries()) == 1

    @property
    def expiry(self) -> Date:
        return self._expiries()[0]

    def is_expired(self) -> bool:  # noqa: D401 - short description
        return self.valuation_date >= self.expiry

    # ------------------------------------------------------------------
    # internals
    def _expiries(self) -> Sequence[Date]:
        if self.expiries and len(self.expiries) > 0:
            return self.expiries
        # default to swap start
        return [self.swap.issue_date]

    def _exercise(self):
        exps = self._expiries()
        if len(exps) == 1:
            return EuropeanExercise(exps[0])
        return BermudanExercise(list(exps))

    def _settlement(self) -> Settlement:
        return (
            Settlement.Physical
            if self.settlement.lower() == "physical"
            else Settlement.Cash
        )

    def _vanilla_swap_for_pricing(
        self,
        strike: Optional[float],
    ) -> VanillaSwap:
        """Build a :class:`VanillaSwap` for payoff evaluation."""
        base = self.swap._vanilla_swap_ql()
        k = base.fairRate() if strike is None else float(strike)

        if self.swap.fixed_leg is self.swap.paying_leg:
            swap_type = VanillaSwap.Payer
        else:
            swap_type = VanillaSwap.Receiver

        v = VanillaSwap(
            swap_type,
            self.swap.fixed_leg.nominal,
            self.swap.fixed_leg.future_schedule,
            k,
            self.swap.fixed_leg.day_counter,
            self.swap.floating_leg.future_schedule,
            self.swap.floating_leg.index,
            self.swap.floating_leg.spread,
            self.swap.floating_leg.day_counter,
        )
        v.setPricingEngine(self.swap.discount_engine)
        return v

    def _engine(self):
        dc = self.swap.fixed_leg.day_counter
        handle = self.swap.discount_curve
        vt = self.volatility
        t = self.vol_type.lower()
        vol = QuoteHandle(SimpleQuote(float(vt)))
        if t == "black":
            return BlackSwaptionEngine(handle, vol, dc)
        if t in ("normal", "bachelier"):
            return BachelierSwaptionEngine(handle, vol, dc)
        raise ValueError("vol_type must be 'black' or 'normal'")

    def _swaption(self) -> QLSwaption:
        vanilla = self._vanilla_swap_for_pricing(self.strike)
        swpt = QLSwaption(vanilla, self._exercise(), self._settlement())
        swpt.setPricingEngine(self._engine())
        return swpt

    # ------------------------------------------------------------------
    # analytics
    def mark_to_market(self) -> float:
        if self.is_expired():
            return 0.0
        v = self._swaption().NPV()
        return v if self.is_long else -v

    def mtm(self) -> float:
        return self.mark_to_market()

    def vega(self) -> float:
        if self.is_expired():
            return 0.0
        v = self._swaption().vega()
        return v if self.is_long else -v

    def implied_volatility(
        self,
        target_npv: float,
        *,
        accuracy: float = 1e-7,
        max_evaluations: int = 500,
        min_vol: float = 1e-6,
        max_vol: float = 5.0,
    ) -> float:
        if self.is_expired():
            return 0.0
        swpt = self._swaption()
        engine = self._engine()
        swpt.setPricingEngine(engine)
        vol = swpt.impliedVolatility(
            float(target_npv),
            self.swap.discount_curve,
            float(self.volatility),
            accuracy,
            max_evaluations,
            min_vol,
            max_vol,
        )
        return float(vol)

    def atm_strike(self) -> float:
        v = self._vanilla_swap_for_pricing(None)
        return float(v.fairRate())
