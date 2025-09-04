from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Type, cast

from pandas import DataFrame, merge, option_context
from QuantLib import (
    Annual,
    Continuous,
    DiscountingSwapEngine,
    QuoteHandle,
    SimpleQuote,
    Swap,
    VanillaSwap,
    YieldTermStructureHandle,
    ZeroSpreadedTermStructure,
)

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg, SwapLeg
from pricingengine.instruments._instrument import Instrument


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
    discount_curve: YieldTermStructureHandle  # required; can be Relinkable

    # ---------- lifecycle & invariants ----------
    def __post_init__(self):
        t1, t2 = type(self.paying_leg), type(self.receiving_leg)
        # Type checks
        if not issubclass(t1, SwapLeg) or not issubclass(t2, SwapLeg):
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must be a subclass of `SwapLeg`"
            )
        else:
            if issubclass(t1, FixedLeg) and issubclass(t2, FixedLeg):
                raise ValueError(
                    "'paying_leg' and 'receiving_leg' cannot be of the same type "
                    "`FixedLeg`"
                )
            elif issubclass(t1, FloatingLeg) and issubclass(t2, FloatingLeg):
                raise ValueError(
                    "'paying_leg' and 'receiving_leg' cannot be of the same type "
                    "`FloatingLeg`"
                )
            else:
                pass
        # Alignment checks
        if self.paying_leg.valuation_date != self.receiving_leg.valuation_date:
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must have the same 'valuation_date'"
            )
        elif self.paying_leg.issue_date != self.receiving_leg.issue_date:
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must have the same 'issue_date'"
            )
        elif self.paying_leg.maturity != self.receiving_leg.maturity:
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must have the same 'maturity'"
            )
        elif self.paying_leg.currency != self.receiving_leg.currency:
            raise ValueError(
                "'paying_leg' and 'receiving_leg' must have the same 'currency'"
            )
        else:
            pass

    # ---------- properties ----------
    @property
    def fixed_leg(self) -> FixedLeg:
        return cast(FixedLeg, self._leg(FixedLeg))

    @property
    def floating_leg(self) -> FloatingLeg:
        return cast(FloatingLeg, self._leg(FloatingLeg))

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

    # ---------- discounting engine ----------
    @cached_property
    def discount_engine(self) -> DiscountingSwapEngine:
        # Works with relinkable handles transparently
        return DiscountingSwapEngine(self.discount_curve)

    # ---------- internals ----------
    def _leg(self, cls: Type[SwapLeg]) -> FixedLeg | FloatingLeg:
        """Return the leg of the requested class; error if missing."""
        if isinstance(self.receiving_leg, cls):
            return self.receiving_leg
        if isinstance(self.paying_leg, cls):
            return self.paying_leg
        raise RuntimeError(f"swap is missing {cls.__name__}")

    def _swap_ql(self) -> Swap:
        """
        Returns a QuantLib `Swap` object.

        `Swap` is a native QuantLib object for pricing interest-rate swaps
        (IRS). `Swap` is generic and consists of cash flow legs. It supports
        features such as:

            - support for variable nominal values for leg payments
            - support for gearing for floating leg payments

        This method is a part of valuation framework for IRS.
        """
        pay = self.paying_leg.cashflows
        rec = self.receiving_leg.cashflows
        sw = Swap(pay, rec)
        sw.setPricingEngine(self.discount_engine)
        return sw

    def _vanilla_swap_ql(self) -> VanillaSwap:
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
        swap_type = (
            VanillaSwap.Payer
            if (self.fixed_leg is self.paying_leg)
            else VanillaSwap.Receiver
        )
        vs = VanillaSwap(
            swap_type,
            self.fixed_leg.nominal,
            self.fixed_leg.future_schedule,
            self.fixed_leg.rate,
            self.fixed_leg.day_counter,
            self.floating_leg.future_schedule,
            self.floating_leg.index,  # index already bound to its (relinkable) handle
            self.floating_leg.spread,
            self.floating_leg.day_counter,
        )
        vs.setPricingEngine(self.discount_engine)
        return vs

    # ---------- analytics ----------
    def mark_to_market(self) -> float:
        if self.is_expired:
            return 0.0
        return self._swap_ql().NPV()

    def mtm(self) -> float:  # pragma: no cover - simple alias
        """Alias to satisfy Instrument interface."""
        return self.mark_to_market()

    def pv01(self) -> float:
        """Fixed-leg PV01 (coupon BPV): ΔNPV for +1 bp in the fixed coupon."""
        leg_index = 0 if (self.fixed_leg is self.paying_leg) else 1
        return self._swap_ql().legBPS(leg_index)

    def dv01(self) -> float:
        """Floating-leg BPV to spread: ΔNPV for +1 bp in the floating spread."""
        leg_index = 0 if (self.floating_leg is self.paying_leg) else 1
        return self._swap_ql().legBPS(leg_index)

    def ir01_discount(self, bump_bp: float = 1.0) -> float:
        """
        Curve BPV to a parallel bump of the *discounting* curve (in zero-yield terms).
        Positive means NPV rises when discount rates fall.
        """
        base = self._swap_ql().NPV()

        # Build a spreaded curve on top of the current discount handle.
        spread = QuoteHandle(SimpleQuote(bump_bp / 10_000.0))
        bumped_ts = ZeroSpreadedTermStructure(
            self.discount_curve,  # Handle<YTS>
            spread,
            Continuous,  # bump in continuous zero-yield space
            Annual,  # unused with Continuous, but required by ctor
            self.discount_curve.dayCounter(),
        )
        bumped_engine = DiscountingSwapEngine(YieldTermStructureHandle(bumped_ts))

        # Rebuild a Swap with the bumped engine (legs are identical).
        pay = self.paying_leg.cashflows
        rec = self.receiving_leg.cashflows
        sw_bumped = Swap(pay, rec)
        sw_bumped.setPricingEngine(bumped_engine)

        bumped = sw_bumped.NPV()
        return (bumped - base) / bump_bp

    def ir01_forecast(self, bump_bp: float = 1.0) -> float:
        """
        Curve BPV to a parallel bump of the *forecasting* (index) curve.
        Uses the floating leg's IborIndex forwarding handle; no external nodes.
        """
        base = self._swap_ql().NPV()

        # Bump the index's forwarding TS via a zero-spread wrapper.
        idx0 = self.floating_leg.index
        fwd_handle = idx0.forwardingTermStructure()  # Handle<YTS>
        spread = QuoteHandle(SimpleQuote(bump_bp / 10_000.0))
        bumped_fwd_ts = ZeroSpreadedTermStructure(
            fwd_handle,  # Handle<YTS>
            spread,
            Continuous,
            Annual,
            fwd_handle.dayCounter(),
        )
        idx_bumped = idx0.clone(YieldTermStructureHandle(bumped_fwd_ts))

        # Rebuild the floating leg with the bumped index so cashflows bind to it.
        fl_bumped = self.floating_leg.with_index(idx_bumped)
        pay_b = (
            fl_bumped.cashflows
            if (self.floating_leg is self.paying_leg)
            else self.paying_leg.cashflows
        )
        rec_b = (
            fl_bumped.cashflows
            if (self.floating_leg is self.receiving_leg)
            else self.receiving_leg.cashflows
        )

        sw_bumped = Swap(pay_b, rec_b)
        sw_bumped.setPricingEngine(self.discount_engine)  # same discounting
        bumped = sw_bumped.NPV()

        return (bumped - base) / bump_bp

    # ---------- diagnostics ----------
    def cashflow_table(self) -> DataFrame:
        """Bloomberg-style cashflow breakdown using the bound discount curve."""
        sw = self._swap_ql()
        df_pay = DataFrame(
            data=({"Date": c.date(), "Pay": -c.amount()} for c in sw.leg(0))
        )
        df_rec = DataFrame(
            data=({"Date": c.date(), "Receive": c.amount()} for c in sw.leg(1))
        )

        h = self.discount_curve
        df = (
            merge(df_pay, df_rec, how="outer", on="Date", sort=True)
            .fillna(0.0)
            .assign(
                Net=lambda x: x.Pay + x.Receive,
                DiscountFactor=lambda x: x.Date.apply(h.discount),
                PresentValue=lambda x: x.Net * x.DiscountFactor,
                Date=lambda x: x.Date.apply(lambda d: d.ISO()),
            )
            .rename(
                columns={
                    "Pay": f"Pay ({self.paying_leg.__class__.__name__})",
                    "Receive": f"Receive ({self.receiving_leg.__class__.__name__})",
                }
            )
            .set_index("Date")
        )
        with option_context("display.float_format", "{:,.2f}".format):
            df["DiscountFactor"] = df.DiscountFactor.map("{:,.6f}".format)
        return df
