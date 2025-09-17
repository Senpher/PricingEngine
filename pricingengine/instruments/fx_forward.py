from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pandas import DataFrame
from QuantLib import (
    Annual,
    Continuous,
    Date,
    QuoteHandle,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
    ZeroSpreadedTermStructure,
)

from pricingengine.instruments._instrument import Instrument
from pricingengine.termstructures.curve_nodes import CurveNodes


@dataclass(frozen=True, kw_only=True)
class FXForward(Instrument):
    """Represent a physically or cash-settled FX forward contract."""

    maturity: Date
    notional: float  # foreign currency amount (positive = long foreign)
    forward_quote: QuoteHandle | float
    spot_quote: QuoteHandle | float
    domestic_curve: YieldTermStructureHandle | CurveNodes
    foreign_curve: YieldTermStructureHandle | CurveNodes
    is_long_foreign: bool = True
    settlement: str = "physical"

    def __post_init__(self) -> None:
        if self.notional == 0.0:
            raise ValueError("notional must be non-zero")

        if self.settlement.lower() not in {"physical", "cash"}:
            raise ValueError("settlement must be 'physical' or 'cash'")

        object.__setattr__(self, "forward_quote", self._ensure_quote_handle(self.forward_quote, "forward_quote"))
        object.__setattr__(self, "spot_quote", self._ensure_quote_handle(self.spot_quote, "spot_quote"))
        object.__setattr__(self, "domestic_curve", self._ensure_curve_handle(self.domestic_curve, "domestic_curve"))
        object.__setattr__(self, "foreign_curve", self._ensure_curve_handle(self.foreign_curve, "foreign_curve"))

        for name, handle in (
            ("domestic_curve", self.domestic_curve),
            ("foreign_curve", self.foreign_curve),
        ):
            try:
                handle.discount(self.maturity)
            except RuntimeError as exc:  # empty relinkable handle
                raise ValueError(f"{name} must be linked to a term structure") from exc

    # ---------- helpers ----------
    @staticmethod
    def _ensure_quote_handle(value: QuoteHandle | float, name: str) -> QuoteHandle:
        if isinstance(value, QuoteHandle):
            return value
        if isinstance(value, (int, float)):
            return QuoteHandle(SimpleQuote(float(value)))
        if isinstance(value, SimpleQuote):
            return QuoteHandle(value)
        raise TypeError(f"{name} must be a QuoteHandle, SimpleQuote, or float")

    @staticmethod
    def _ensure_curve_handle(value: YieldTermStructureHandle | CurveNodes, name: str) -> YieldTermStructureHandle:
        if isinstance(value, YieldTermStructureHandle):
            return value
        if isinstance(value, CurveNodes):
            return value.to_handle()
        if hasattr(value, "discount") and hasattr(value, "dayCounter"):
            return YieldTermStructureHandle(value)  # type: ignore[arg-type]
        raise TypeError(f"{name} must be a YieldTermStructureHandle or CurveNodes")

    # ---------- properties ----------
    @property
    def valuation_date(self) -> Date:
        return Settings.instance().evaluationDate

    @property
    def is_expired(self) -> bool:  # type: ignore[override]
        return self.valuation_date >= self.maturity

    @property
    def direction(self) -> float:
        return 1.0 if self.is_long_foreign else -1.0

    @property
    def spot(self) -> float:
        return float(self.spot_quote.value())

    @property
    def forward_rate(self) -> float:
        return float(self.forward_quote.value())

    def domestic_discount_factor(self, curve: YieldTermStructureHandle | None = None) -> float:
        handle = curve if curve is not None else self.domestic_curve
        return float(handle.discount(self.maturity))

    def foreign_discount_factor(self, curve: YieldTermStructureHandle | None = None) -> float:
        handle = curve if curve is not None else self.foreign_curve
        return float(handle.discount(self.maturity))

    # ---------- pricing internals ----------
    def _forward_market(
        self,
        *,
        spot: QuoteHandle | None = None,
        domestic_curve: YieldTermStructureHandle | None = None,
        foreign_curve: YieldTermStructureHandle | None = None,
    ) -> float:
        spot_handle = spot if spot is not None else self.spot_quote
        dom = domestic_curve if domestic_curve is not None else self.domestic_curve
        fra = foreign_curve if foreign_curve is not None else self.foreign_curve

        df_dom = float(dom.discount(self.maturity))
        df_for = float(fra.discount(self.maturity))
        if df_dom <= 0.0 or df_for <= 0.0:
            raise ValueError("discount factors must be positive")
        return float(spot_handle.value()) * df_for / df_dom

    def _npv(
        self,
        *,
        spot: QuoteHandle | None = None,
        forward: QuoteHandle | None = None,
        domestic_curve: YieldTermStructureHandle | None = None,
        foreign_curve: YieldTermStructureHandle | None = None,
    ) -> float:
        forward_handle = forward if forward is not None else self.forward_quote
        fwd_mkt = self._forward_market(
            spot=spot,
            domestic_curve=domestic_curve,
            foreign_curve=foreign_curve,
        )
        k = float(forward_handle.value())
        df_dom = self.domestic_discount_factor(domestic_curve)
        return self.direction * self.notional * (fwd_mkt - k) * df_dom

    # ---------- analytics ----------
    def mark_to_market(self) -> float:  # type: ignore[override]
        if self.is_expired:
            return 0.0
        return float(self._npv())

    def mtm(self) -> float:
        """Alias for backwards compatibility."""
        return self.mark_to_market()

    def par_forward(self) -> float:
        """Fair forward FX rate implied by current spot and curves."""
        return self._forward_market()

    def forward_points(self) -> float:
        return self.par_forward() - self.spot

    def spot_delta(self) -> float:
        if self.is_expired:
            return 0.0
        return self.direction * self.notional * self.foreign_discount_factor()

    def strike_delta(self) -> float:
        if self.is_expired:
            return 0.0
        return -self.direction * self.notional * self.domestic_discount_factor()

    def ir01_domestic(self, bump_bp: float = 1.0) -> float:
        if self.is_expired:
            return 0.0
        base = self._npv()
        bumped = self._npv(domestic_curve=self._bump_curve(self.domestic_curve, bump_bp))
        return (bumped - base) / bump_bp

    def ir01_foreign(self, bump_bp: float = 1.0) -> float:
        if self.is_expired:
            return 0.0
        base = self._npv()
        bumped = self._npv(foreign_curve=self._bump_curve(self.foreign_curve, bump_bp))
        return (bumped - base) / bump_bp

    def currency_exposure(self) -> dict[str, float]:
        """
        Return the forward's currency exposures (signed notionals).

        Domestic exposure is reported in domestic currency units, foreign exposure
        in foreign currency units. Positive values indicate long positions.
        """

        sign = self.direction
        return {
            "foreign": sign * float(self.notional),
            "domestic": -sign * float(self.notional) * self.forward_rate,
        }

    def cashflow_table(self) -> DataFrame:
        """Return a one-line cash-flow table for the forward maturity."""

        pv = self.mark_to_market()
        df_dom = self.domestic_discount_factor()
        df_for = self.foreign_discount_factor()
        data = [
            {
                "Date": self.maturity.ISO(),
                "ForeignFlow": self.currency_exposure()["foreign"],
                "DomesticFlow": self.currency_exposure()["domestic"],
                "DF(domestic)": df_dom,
                "DF(foreign)": df_for,
                "Forward(market)": self.par_forward(),
                "Forward(strike)": self.forward_rate,
                "PV": pv,
            }
        ]
        return DataFrame(data).set_index("Date")

    # ---------- scenario utilities ----------
    def with_spot(self, spot: QuoteHandle | float) -> "FXForward":
        return replace(self, spot_quote=spot)

    def with_forward(self, forward: QuoteHandle | float) -> "FXForward":
        return replace(self, forward_quote=forward)

    def with_notional(self, notional: float) -> "FXForward":
        return replace(self, notional=notional)

    # ---------- static helpers ----------
    @staticmethod
    def _bump_curve(curve: YieldTermStructureHandle, bump_bp: float) -> YieldTermStructureHandle:
        spread = QuoteHandle(SimpleQuote(bump_bp / 10_000.0))
        link = curve.currentLink()
        bumped = ZeroSpreadedTermStructure(curve, spread, Continuous, Annual, link.dayCounter())
        return YieldTermStructureHandle(bumped)

    @classmethod
    def from_nodes(
        cls,
        *,
        maturity: Date,
        notional: float,
        forward_rate: float,
        spot: float,
        domestic_nodes: CurveNodes,
        foreign_nodes: CurveNodes,
        is_long_foreign: bool = True,
        settlement: str = "physical",
    ) -> "FXForward":
        """Convenience constructor using :class:`CurveNodes`."""

        return cls(
            maturity=maturity,
            notional=notional,
            forward_quote=forward_rate,
            spot_quote=spot,
            domestic_curve=domestic_nodes,
            foreign_curve=foreign_nodes,
            is_long_foreign=is_long_foreign,
            settlement=settlement,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize key attributes for debugging or logging."""

        return {
            "valuation_date": self.valuation_date.ISO(),
            "maturity": self.maturity.ISO(),
            "notional": self.notional,
            "forward_rate": self.forward_rate,
            "spot": self.spot,
            "is_long_foreign": self.is_long_foreign,
            "settlement": self.settlement,
        }
