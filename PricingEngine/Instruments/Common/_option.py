from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from QuantLib import (
    BlackScholesMertonProcess,
    Date,
    Settings,
)
from QuantLib import (
    VanillaOption as QLVanillaOption,
)

from PricingEngine.Instruments.Common import Instrument


@dataclass(frozen=True, kw_only=True)
class Option(Instrument, ABC):
    """
    Option base class for QL `VanillaOption`-style Instruments.

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

    # cached QuantLib primitives (lazily built)
    _ql_opt_cache: QLVanillaOption | None = field(default=None, init=False, repr=False, compare=False)
    _engine_cache: Any | None = field(default=None, init=False, repr=False, compare=False)
    _process_cache: BlackScholesMertonProcess | None = field(default=None, init=False, repr=False, compare=False)
    _cache_eval_date: Date | None = field(default=None, init=False, repr=False, compare=False)

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

    def _make_process(self) -> BlackScholesMertonProcess:
        return self._process()

    def _clear_cache(self) -> None:
        object.__setattr__(self, "_ql_opt_cache", None)
        object.__setattr__(self, "_engine_cache", None)
        object.__setattr__(self, "_process_cache", None)
        object.__setattr__(self, "_cache_eval_date", None)

    def _ensure_built(self) -> None:
        eval_date = Settings.instance().evaluationDate
        if self._ql_opt_cache is not None and self._cache_eval_date == eval_date:
            return

        process = self._make_process()
        engine = self._engine(process)
        ql_option = QLVanillaOption(self._payoff, self._exercise)
        ql_option.setPricingEngine(engine)

        object.__setattr__(self, "_process_cache", process)
        object.__setattr__(self, "_engine_cache", engine)
        object.__setattr__(self, "_ql_opt_cache", ql_option)
        object.__setattr__(self, "_cache_eval_date", eval_date)

    def _ql_option(self) -> QLVanillaOption:
        self._ensure_built()
        assert self._ql_opt_cache is not None  # for mypy / linters
        return self._ql_opt_cache

    def _position_multiplier(self) -> int:
        # uniform scaling across Instruments
        return int(self.quantity) * int(self.contract_size)

    # ---------- public API ----------
    def npv_per_unit(self) -> float:
        if self.is_expired:
            return 0.0
        return float(self._ql_option().NPV())

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
    _trace: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=256),
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def log(self):
        """Return a snapshot of the recent greek-computation trace for this instance."""
        return list(self._trace)
