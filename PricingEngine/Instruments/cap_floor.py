"""Interest-rate caps and floors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property

from QuantLib import (
    BlackCapFloorEngine,
    CapFloor,
    CashFlow,
    Date,
    OptionletVolatilityStructureHandle,
    Settings,
    YieldTermStructureHandle,
)
from QuantLib import (
    Cap as QLCap,
)
from QuantLib import (
    Floor as QLFloor,
)

from PricingEngine.Instruments.Common import FloatingLeg, Instrument


@dataclass(frozen=True, kw_only=True)
class _CapFloorBase(Instrument, ABC):
    """Base class for cap/floor wrappers around QuantLib instruments."""

    floating_leg: FloatingLeg
    strike: Sequence[float]
    discount_curve: YieldTermStructureHandle
    vol: OptionletVolatilityStructureHandle
    _cashflows: tuple[CashFlow, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.floating_leg, FloatingLeg):
            raise TypeError("Floating leg must be an instance of FloatingLeg")

        cashflows = tuple(self.floating_leg.cashflows)
        if len(self.strike) != len(cashflows):
            raise ValueError("Strike sequence length must match the number of future floating coupons")

        object.__setattr__(self, "_cashflows", cashflows)

    # ---------- properties ----------
    @property
    def valuation_date(self) -> Date:
        return Settings.instance().evaluationDate

    @property
    def maturity(self) -> Date:
        return self.floating_leg.maturity

    @property
    def is_expired(self) -> bool:
        return self.valuation_date > self.maturity

    @cached_property
    def pricing_engine(self) -> BlackCapFloorEngine:
        return BlackCapFloorEngine(self.discount_curve, self.vol)

    @abstractmethod
    def _ql_cap_floor(self) -> CapFloor:
        raise NotImplementedError

    # ---------- public API ----------
    def npv(self) -> float:
        if self.is_expired or not self._cashflows:
            return 0.0

        return self._ql_cap_floor().NPV()


@dataclass(frozen=True, kw_only=True)
class Cap(_CapFloorBase):
    """Interest-rate cap priced via QuantLib's :class:`Cap`."""

    def _ql_cap_floor(self) -> CapFloor:
        cap = QLCap(list(self._cashflows), self.strike)
        cap.setPricingEngine(self.pricing_engine)
        return cap


@dataclass(frozen=True, kw_only=True)
class Floor(_CapFloorBase):
    """Interest-rate floor priced via QuantLib's :class:`Floor`."""

    def _ql_cap_floor(self) -> CapFloor:
        floor = QLFloor(list(self._cashflows), self.strike)
        floor.setPricingEngine(self.pricing_engine)
        return floor
