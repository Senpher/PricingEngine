from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from QuantLib import DiscountingSwapEngine, Index, Swap, VanillaSwap

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg, SwapLeg
from pricingengine.instruments._instrument import Instrument
from pricingengine.structures.curve_nodes import CurveNodes


@dataclass(frozen=True, kw_only=True, slots=True)
class InterestRateSwap(Instrument):
    """Vanilla single-currency IRS with one fixed and one floating leg."""

    paying_leg: FixedLeg | FloatingLeg
    receiving_leg: FixedLeg | FloatingLeg

    # ---------- lifecycle & invariants ----------
    def __post_init__(self):
        t1, t2 = type(self.paying_leg), type(self.receiving_leg)
        if not issubclass(t1, SwapLeg) or not issubclass(t2, SwapLeg):
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must be a subclass of `SwapLeg`"
            )
        if issubclass(t1, FixedLeg) and issubclass(t2, FixedLeg):
            raise ValueError("both legs cannot be FixedLeg")
        if issubclass(t1, FloatingLeg) and issubclass(t2, FloatingLeg):
            raise ValueError("both legs cannot be FloatingLeg")
        if self.paying_leg.valuation_date != self.receiving_leg.valuation_date:
            raise ValueError("legs must share valuation_date")
        if self.paying_leg.issue_date != self.receiving_leg.issue_date:
            raise ValueError("legs must share issue_date")
        if self.paying_leg.maturity != self.receiving_leg.maturity:
            raise ValueError("legs must share maturity")
        if self.paying_leg.currency != self.receiving_leg.currency:
            raise ValueError("legs must share currency")

    # ---------- properties ----------
    @property
    def fixed_leg(self) -> FixedLeg:
        return self._leg(FixedLeg)  # type: ignore[return-value]

    @property
    def floating_leg(self) -> FloatingLeg:
        return self._leg(FloatingLeg)  # type: ignore[return-value]

    @property
    def valuation_date(self):
        return self.receiving_leg.valuation_date

    @property
    def currency(self):
        return self.receiving_leg.currency

    @property
    def issue_date(self):
        return self.receiving_leg.issue_date

    @property
    def maturity(self):
        return self.receiving_leg.maturity

    @property
    def is_expired(self) -> bool:
        return self.valuation_date >= self.maturity

    # ---------- internals ----------
    def _leg(self, cls: Type[SwapLeg]) -> FixedLeg | FloatingLeg:
        if isinstance(self.receiving_leg, cls):
            return self.receiving_leg
        if isinstance(self.paying_leg, cls):
            return self.paying_leg
        raise RuntimeError(f"swap is missing {cls.__name__}")

    @staticmethod
    def _discount_engine(discount_nodes: CurveNodes) -> DiscountingSwapEngine:
        """Build a discounting engine from CurveNodes (discounting role)."""
        if discount_nodes.role != "discounting":
            raise ValueError("discount_nodes must have role='discounting'")
        return DiscountingSwapEngine(discount_nodes.to_handle())

    def _swap_ql(self, forecast_index: Index, discount_nodes: CurveNodes) -> Swap:
        """QuantLib Swap with correct engine and cashflow legs."""
        # NOTE: ensure forecast_index is already linked to a forecasting curve
        if isinstance(self.paying_leg, FixedLeg):
            paying = self.paying_leg.cashflows()
        else:
            paying = self.paying_leg.cashflows(forecast_index=forecast_index)

        if isinstance(self.receiving_leg, FixedLeg):
            receiving = self.receiving_leg.cashflows()
        else:
            receiving = self.receiving_leg.cashflows(forecast_index=forecast_index)

        swap = Swap(paying, receiving)
        swap.setPricingEngine(self._discount_engine(discount_nodes))
        return swap

    def _vanilla_swap_ql(
        self, forecast_index: Index, discount_nodes: CurveNodes
    ) -> VanillaSwap:
        """QuantLib VanillaSwap (used for fairRate/fairSpread & swaptions)."""
        swap_type = (
            VanillaSwap.Payer
            if self.fixed_leg is self.paying_leg
            else VanillaSwap.Receiver
        )
        swap = VanillaSwap(
            swap_type,
            self.fixed_leg.nominal,
            self.fixed_leg.future_schedule,
            self.fixed_leg.rate,
            self.fixed_leg.day_counter,
            self.floating_leg.future_schedule,
            forecast_index,
            self.floating_leg.spread,
            self.floating_leg.day_counter,
        )
        swap.setPricingEngine(self._discount_engine(discount_nodes))
        return swap

    # ---------- analytics ----------
    def price(self, forecast_index: Index, discount_nodes: CurveNodes) -> float:
        """Alias for mtm()."""
        return self.mtm(forecast_index, discount_nodes)

    def mtm(self, forecast_index: Index, discount_nodes: CurveNodes) -> float:
        """Mark-to-market NPV of the swap."""
        if self.is_expired:
            return 0.0
        return self._swap_ql(forecast_index, discount_nodes).NPV()

    def fixed_leg_bpv(self, forecast_index: Index, discount_nodes: CurveNodes) -> float:
        """BPV of the fixed leg (≈ annuity for small shifts)."""
        idx = 0 if self.fixed_leg is self.paying_leg else 1
        return self._swap_ql(forecast_index, discount_nodes).legBPS(idx)

    def float_leg_bpv(self, forecast_index: Index, discount_nodes: CurveNodes) -> float:
        """BPV of the floating leg."""
        idx = 0 if self.floating_leg is self.paying_leg else 1
        return self._swap_ql(forecast_index, discount_nodes).legBPS(idx)

    def pv01(
        self, forecast_index: Index, discount_nodes: CurveNodes, bump_bp: float = 1.0
    ) -> float:
        """Net PV01 via a parallel bump of the discount curve.

        Positive means the NPV rises when discount rates fall.
        """
        base = self._swap_ql(forecast_index, discount_nodes).NPV()
        bumped = self._swap_ql(forecast_index, discount_nodes.bump(bump_bp)).NPV()
        return (bumped - base) / bump_bp  # per bp
