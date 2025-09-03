from __future__ import annotations

from QuantLib import (DiscountingSwapEngine, Index, Swap, VanillaSwap, ZeroCurve)
from dataclasses import dataclass
from pandas import DataFrame, merge, option_context
from typing import Type, Optional

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg, SwapLeg
from pricingengine.instruments._instrument import Instrument
from pricingengine.termstructures.curve_nodes import CurveNodes


@dataclass(frozen=True, kw_only=True)
class InterestRateSwap(Instrument):
    """
    Class that represents a vanilla interest-rate swap contract.

    Swaps instruments involve two legs, the so-called paying and receiving leg,
    which exchange cash flows based on the contract information. In a vanilla
    interest-rate swap, where the legs are exchanging cash flows in the same
    currency, one leg pays a fixed rate while the other pays a floating rate
    related to the Libor rate for that currency (e.g., Euribor for EUR, Stibor
    for SEK).

    Swaps with fixed nominal values are instantiated with `FixedLeg` and
    `FloatingLeg`, which inherit from `SwapLeg`.

    Swaps with amortized nominal values are instantiated with
    `AmortizedFixedLeg` and `AmortizedFloatingLeg`, which inherit respectively
    from `FixedLeg` and `FloatingLeg`.
    """

    paying_leg: FixedLeg | FloatingLeg
    receiving_leg: FixedLeg | FloatingLeg

    # ---------- lifecycle & invariants ----------
    def __post_init__(self):
        t1, t2 = type(self.paying_leg), type(self.receiving_leg)
        # Type checks
        if not issubclass(t1, SwapLeg) or not issubclass(t2, SwapLeg):
            raise ValueError("'paying_leg' and 'receiving_leg' must be a subclass of `SwapLeg`")
        else:
            if issubclass(t1, FixedLeg) and issubclass(t2, FixedLeg):
                raise ValueError("'paying_leg' and 'receiving_leg' cannot be of the same type `FixedLeg`")
            elif issubclass(t1, FloatingLeg) and issubclass(t2, FloatingLeg):
                raise ValueError("'paying_leg' and 'receiving_leg' cannot be of the same type `FloatingLeg`")
            else:
                pass
        # Alignment checks
        if self.paying_leg.valuation_date != self.receiving_leg.valuation_date:
            raise ValueError("'paying_leg' and 'receiving_leg' must have the same 'valuation_date'")
        elif self.paying_leg.issue_date != self.receiving_leg.issue_date:
            raise ValueError("'paying_leg' and 'receiving_leg' must have the same 'issue_date'")
        elif self.paying_leg.maturity != self.receiving_leg.maturity:
            raise ValueError("'paying_leg' and 'receiving_leg' must have the same 'maturity'")
        elif self.paying_leg.currency != self.receiving_leg.currency:
            raise ValueError("'paying_leg' and 'receiving_leg' must have the same 'currency'")
        else:
            pass

    # ---------- properties ----------
    @property
    def fixed_leg(self) -> FixedLeg:
        return self._leg(FixedLeg)

    @property
    def floating_leg(self) -> FloatingLeg:
        return self._leg(FloatingLeg)

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
    def is_expired(self):
        return self.valuation_date >= self.maturity

    # ---------- internals ----------
    def _leg(self, cls: Type[SwapLeg]) -> FixedLeg | FloatingLeg:
        """Return the leg of the requested class; error if missing."""
        if isinstance(self.receiving_leg, cls):
            return self.receiving_leg
        if isinstance(self.paying_leg, cls):
            return self.paying_leg
        raise RuntimeError(f"swap is missing {cls.__name__}")

    def _resolve_index(self, forecast_index: Optional[Index]) -> Index:
        if forecast_index is not None:
            return forecast_index
        # use the leg’s bound index if available
        fl = self.floating_leg
        idx = getattr(fl, "index", None)  # FloatingLeg.index: Optional[Index]
        if idx is None:
            raise ValueError("Missing forecasting Index: pass forecast_index=... or set floating_leg.index.")
        return idx

    @staticmethod
    def _discount_engine(discount_nodes: CurveNodes) -> DiscountingSwapEngine:
        """Build (or reuse) a discounting engine from CurveNodes."""
        return DiscountingSwapEngine(discount_nodes.yts_handle())

    # ---------- QL builders ----------
    def _swap_ql(self, forecast_index: Optional[Index], discount_nodes: CurveNodes) -> Swap:
        """
        Returns a QuantLib `Swap` object.

        `Swap` is a native QuantLib object for pricing interest-rate swaps
        (IRS). `Swap` is generic and consists of cash flow legs. It supports
        features such as:

            - support for variable nominal values for leg payments
            - support for gearing for floating leg payments

        This method is a part of valuation framework for IRS.
        """
        idx = self._resolve_index(forecast_index)

        if isinstance(self.paying_leg, FixedLeg):
            paying_leg = self.paying_leg.cashflows()
        else:  # must be FloatingLeg by invariant
            paying_leg = self.paying_leg.cashflows(forecast_index=idx)

        if isinstance(self.receiving_leg, FixedLeg):
            receiving_leg = self.receiving_leg.cashflows()
        else:  # must be FloatingLeg by invariant
            receiving_leg = self.receiving_leg.cashflows(forecast_index=idx)

        swap = Swap(paying_leg, receiving_leg)
        swap.setPricingEngine(self._discount_engine(discount_nodes))
        return swap

    def _vanilla_swap_ql(self, forecast_index: Optional[Index], discount_nodes: CurveNodes) -> VanillaSwap:
        """
        Returns a QuantLib `VanillaSwap` object.

        `VanillaSwap` is a native QuantLib object that has `NPV` method,
        similar to `Swap` object, that can be used for pricing of vanilla
        interest-rate swaps (IRS). However, `VanillaSwap` does not have support
        amortization nor interest-rate leverage and therefore is not used for
        IRS valuation.

        `VanillaSwap` object also includes `fairRate` and `fairSpread` methods
        and is therefore used for construction and valuation of swaptions.
        """
        idx = self._resolve_index(forecast_index)

        if self.fixed_leg is self.paying_leg:
            swap_type = VanillaSwap.Payer
        else:
            swap_type = VanillaSwap.Receiver

        swap = VanillaSwap(swap_type, self.fixed_leg.nominal, self.fixed_leg.future_schedule, self.fixed_leg.rate,
                           self.fixed_leg.day_counter, self.floating_leg.future_schedule, idx,
                           self.floating_leg.spread,
                           self.floating_leg.day_counter, )
        swap.setPricingEngine(self._discount_engine(discount_nodes))
        return swap

    @staticmethod
    def debug(swap: InterestRateSwap, forecast_index: Index, discount_nodes: CurveNodes) -> None:
        """
        Display future payments for the swap, including the amounts payed,
        amounts received, net amounts, discount factors, and present values at
        each payment date.

        The format is the same as in Bloomberg Terminal SWPM function.
        """
        swap_ql = swap._swap_ql(forecast_index=forecast_index, discount_nodes=discount_nodes)

        discount_curve_ql = ZeroCurve(discount_nodes.dates, discount_nodes.quotes, discount_nodes.day_counter)

        df_pay = DataFrame(data=({"Date": c.date(), "Pay": -c.amount()} for c in swap_ql.leg(0)))
        df_receive = DataFrame(data=({"Date": c.date(), "Receive": c.amount()} for c in swap_ql.leg(1)))

        df = (merge(df_pay, df_receive, how="outer", on="Date", sort=True)
              .fillna(0)  # when schedules in the swap are different
              .assign(Net=lambda x: x.Pay + x.Receive,
                      DiscountFactor=lambda x: x.Date.apply(discount_curve_ql.discount),
                      PresentValue=lambda x: x.Net * x.DiscountFactor,
                      Date=lambda x: x.Date.apply(lambda date: date.ISO()), )
              .rename(columns={"Pay": f"Pay ({swap.paying_leg.__class__.__name__})",
                               "Receive": f"Receive ({swap.receiving_leg.__class__.__name__})", })
              .set_index("Date"))

        with option_context("display.float_format", "{:,.2f}".format):
            df["DiscountFactor"] = df.DiscountFactor.map("{:,.6f}".format)
            print(df)

    def getCashFlows(self, forecast_index: Index, discount_nodes: CurveNodes) -> DataFrame:
        swap_ql = self._swap_ql(forecast_index=forecast_index, discount_nodes=discount_nodes)

        discount_curve_ql = ZeroCurve(discount_nodes.dates, discount_nodes.quotes, discount_nodes.day_counter)

        df_pay = DataFrame(data=({"Date": c.date(), "Pay": -c.amount()} for c in swap_ql.leg(0)))
        df_receive = DataFrame(data=({"Date": c.date(), "Receive": c.amount()} for c in swap_ql.leg(1)))

        df = (merge(df_pay, df_receive, how="outer", on="Date", sort=True)
              .fillna(0)  # when schedules in the swap are different
              .assign(Net=lambda x: x.Pay + x.Receive,
                      DiscountFactor=lambda x: x.Date.apply(discount_curve_ql.discount),
                      PresentValue=lambda x: x.Net * x.DiscountFactor,
                      Date=lambda x: x.Date.apply(lambda date: date.ISO()), )
              .rename(columns={"Pay": f"Pay ({self.paying_leg.__class__.__name__})",
                               "Receive": f"Receive ({self.receiving_leg.__class__.__name__})", })
              .set_index("Date"))
        return df

    def mark_to_market(self, discount_nodes: CurveNodes, forecast_index: Optional[Index] = None) -> float:
        """Returns mark-to-market value of the swap."""
        if self.is_expired:
            return 0.0
        else:
            return self._swap_ql(forecast_index=forecast_index, discount_nodes=discount_nodes).NPV()

    def mtm(self, forecast_index: Optional[Index], discount_nodes: CurveNodes) -> float:  # pragma: no cover - simple alias
        """Alias to satisfy Instrument interface."""
        return self.mark_to_market(discount_nodes=discount_nodes, forecast_index=forecast_index)

    def pv01(
            self,
            discount_nodes: CurveNodes,
            forecast_index: Optional[Index] = None,
    ) -> float:
        """Fixed-leg PV01 (coupon BPV): NPV change for +1 bp in the fixed coupon."""
        leg_index = 0 if (self.fixed_leg is self.paying_leg) else 1
        return self._swap_ql(forecast_index, discount_nodes).legBPS(leg_index)

    def dv01(
            self,
            discount_nodes: CurveNodes,
            forecast_index: Optional[Index] = None,
    ) -> float:
        """Floating-leg BPV to spread: NPV change for +1 bp in the floating spread."""
        leg_index = 0 if (self.floating_leg is self.paying_leg) else 1
        return self._swap_ql(forecast_index, discount_nodes).legBPS(leg_index)

    def ir01_discount(
            self,
            discount_nodes: CurveNodes,
            forecast_index: Optional[Index] = None,
            bump_bp: float = 1.0,
    ) -> float:
        """
        Curve BPV to a parallel bump of the *discounting* curve.
        Positive means NPV rises when discount rates fall.
        """
        base = self._swap_ql(forecast_index, discount_nodes).NPV()
        bumped_nodes = discount_nodes.bump(bump_bp)
        bumped = self._swap_ql(forecast_index, bumped_nodes).NPV()
        return (bumped - base) / bump_bp

    def ir01_forecast(
            self,
            forecast_nodes: CurveNodes,
            discount_nodes: CurveNodes,
            base_index: Optional[Index] = None,
            bump_bp: float = 1.0,
    ) -> float:
        """
        Curve BPV to a parallel bump of the *forecasting* (index) curve.
        """
        # resolve the base index (either provided or bound to the leg)
        idx0 = self._resolve_index(base_index)
        # build bumped forecasting handle and clone the index on it
        idx_bumped = idx0.clone(forecast_nodes.bump(bump_bp).yts_handle())
        base = self._swap_ql(idx0, discount_nodes).NPV()
        bumped = self._swap_ql(idx_bumped, discount_nodes).NPV()
        return (bumped - base) / bump_bp
