from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, Dict, Any

from QuantLib import (
    Date,
    Settings,
    VanillaOption as QLVanillaOption,
    BlackScholesMertonProcess,
)

from pricingengine.instruments._instrument import Instrument


@dataclass(frozen=True)
class OptionEngineParameters:
    """
    Canonical, ergonomic container for engine selection + knobs.
    Use the class methods to create valid instances.

    kind:        'analytic' | 'fd' | 'tree' | 'baw' | 'bjerksund'
    nt, nx:      finite-difference grid sizes   (only for kind=='fd')
    steps:       binomial/trinomial steps       (only for kind=='tree')
    tree_method: 'jr'|'crr'|'tian'|'trigeorgis'|'lr'|'joshi' (only for 'tree')
    """

    kind: str
    nt: Optional[int] = None
    nx: Optional[int] = None
    steps: Optional[int] = None
    tree_method: Optional[str] = None

    # ---------- factories ----------
    @classmethod
    def analytic(cls) -> "OptionEngineParameters":
        return cls(kind="analytic")

    @classmethod
    def fd(cls, nt: int = 200, nx: int = 400) -> "OptionEngineParameters":
        if nt <= 0 or nx <= 0:
            raise ValueError("FD grid sizes must be positive")
        return cls(kind="fd", nt=nt, nx=nx)

    @classmethod
    def tree(cls, method: str = "lr", steps: int = 501) -> "OptionEngineParameters":
        if steps <= 2:
            raise ValueError("tree steps must be > 2")
        method = method.lower()
        if method not in {"jr", "crr", "tian", "trigeorgis", "lr", "joshi"}:
            raise ValueError(
                "tree_method must be one of jr, crr, tian, trigeorgis, lr, joshi"
            )
        return cls(kind="tree", steps=steps, tree_method=method)

    @classmethod
    def baw(cls) -> "OptionEngineParameters":
        return cls(kind="baw")

    @classmethod
    def bjerksund(cls) -> "OptionEngineParameters":
        return cls(kind="bjerksund")

    # ---------- helpers ----------
    def tree_tag(self, default: Optional[str] = None) -> str:
        mapping = {
            "jr": "JR",
            "crr": "CRR",
            "tian": "Tian",
            "trigeorgis": "Trigeorgis",
            "lr": "LR",
            "joshi": "Joshi4",
        }
        if self.tree_method is None:
            if default is None:
                raise ValueError(
                    "tree_tag() requires tree_method to be set or default provided"
                )
            return default
        return mapping[self.tree_method.lower()]

    # ---------- validation ----------
    def validate_for(self, style: str) -> None:
        """
        Ensure the engine choice is compatible with the option style.
        style: 'european' | 'euro_digital' | 'american' | 'bermudan'
        """
        k = self.kind
        style = style.lower()

        if k == "analytic":
            if style in {"american", "bermudan"}:
                # no closed-form analytic engine for these (in this codebase)
                raise ValueError("analytic engine not supported for American/Bermudan")
            return

        if k == "fd":
            if (self.nt is None) or (self.nx is None):
                raise ValueError("fd engine requires nt and nx")
            return

        if k == "tree":
            if style in {"european", "euro_digital"}:
                # not implemented
                raise ValueError(
                    "analytic engine not supported for european/euro_digital"
                )
            if (self.steps is None) or (self.tree_method is None):
                raise ValueError("tree engine requires steps and tree_method")
            return

        if k in {"baw", "bjerksund"}:
            if style != "american":
                raise ValueError(f"{k} engine only supported for American options")
            return

        raise ValueError(f"unknown engine kind: {k}")


@dataclass(frozen=True, kw_only=True)
class Option(Instrument, ABC):
    """
    Option base class for QL `VanillaOption`-style instruments.

    Responsibilities handled here (so subclasses stay tiny):
      • Position scaling via `quantity * contract_size`.
      • Uniform expiry convention (not expired on the expiry date).
      • Building a QL `VanillaOption` from `_payoff()` + `_exercise()` and
        applying the subclass-provided engine and stochastic process.

    Subclasses must provide:
      - quantity: int (position sign & size)
      - contract_size: int (default 1; e.g., equities often 100)
      - currency: str (pricing currency of the option)
      - _payoff() -> QuantLib.Payoff
      - _exercise() -> QuantLib.Exercise
      - _engine(process) -> QuantLib.PricingEngine
      - _process() -> QuantLib.GeneralizedBlackScholesProcess (or compatible)
      - _expiry_date() -> QuantLib.Date (last exercise date)
    """

    quantity: int
    contract_size: int = 1  # set to 100 in equity options; 1 for FX/index by default

    # ---------- timeline / identity ----------
    @property
    def valuation_date(self) -> Date:
        # Always reflect the current global eval date
        return Settings.instance().evaluationDate

    @property
    def is_expired(self) -> bool:
        # repo-wide convention: not expired on the expiry date
        return self.valuation_date > self._expiry_date()

    @abstractmethod
    def _expiry_date(self) -> Date: ...

    @property
    @abstractmethod
    def _payoff(self): ...

    @property
    @abstractmethod
    def _exercise(self): ...

    @abstractmethod
    def _engine(self, process: BlackScholesMertonProcess): ...

    @abstractmethod
    def _process(self) -> BlackScholesMertonProcess: ...

    @abstractmethod
    def npv_per_unit(self) -> float: ...

    def _ql_option(self) -> QLVanillaOption:
        opt = QLVanillaOption(self._payoff, self._exercise())
        opt.setPricingEngine(self._engine)
        return opt

    def _position_multiplier(self) -> int:
        # uniform scaling across instruments
        return int(self.quantity) * int(self.contract_size)

    # ---------- public API ----------
    def npv(self) -> float:
        return self._position_multiplier() * self.npv_per_unit()

    # Per-contract greeks; subclasses can override/extend
    # The defaults try to use the QL analytic greeks when available.
    def delta(self) -> float:
        if self.is_expired:
            return 0.0
        try:
            return float(self._ql_option().delta())
        except Exception:
            raise NotImplementedError("Delta not available for this engine/model.")

    def gamma(self) -> float:
        if self.is_expired:
            return 0.0
        try:
            return float(self._ql_option().gamma())
        except Exception:
            raise NotImplementedError("Gamma not available for this engine/model.")

    def vega(self) -> float:
        if self.is_expired:
            return 0.0
        try:
            return float(self._ql_option().vega())
        except Exception:
            raise NotImplementedError("Vega not available for this engine/model.")

    def rho(self) -> float:
        if self.is_expired:
            return 0.0
        try:
            return float(self._ql_option().rho())
        except Exception:
            raise NotImplementedError("Rho not available for this engine/model.")

    def theta(self) -> float:
        if self.is_expired:
            return 0.0
        try:
            return float(self._ql_option().theta())
        except Exception:
            raise NotImplementedError("Theta not available for this engine/model.")

    # Scaled greeks (match `npv()` scaling)
    def scaled_delta(self) -> float:
        return self._position_multiplier() * self.delta()

    def scaled_gamma(self) -> float:
        return self._position_multiplier() * self.gamma()

    def scaled_vega(self) -> float:
        return self._position_multiplier() * self.vega()

    def scaled_rho(self) -> float:
        return self._position_multiplier() * self.rho()

    def scaled_theta(self) -> float:
        return self._position_multiplier() * self.theta()

    # Greek log
    _trace: Deque[Dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=256),
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def log(self):
        """Return a snapshot of the recent greek-computation trace for this instance."""
        return list(self._trace)
