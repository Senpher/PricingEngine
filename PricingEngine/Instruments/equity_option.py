from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from typing import ClassVar

from QuantLib import (  # Core dates/settings
    Actual365Fixed,
    AmericanExercise,
    AnalyticEuropeanEngine,
    Annual,
    BaroneAdesiWhaleyApproximationEngine,
    BermudanExercise,  # Engines
    BinomialVanillaEngine,
    BjerksundStenslandApproximationEngine,
    BlackConstantVol,
    BlackScholesMertonProcess,  # Payoffs
    BlackVolTermStructureHandle,
    CashOrNothingPayoff,  # Exercises
    Date,
    EuropeanExercise,
    FdBlackScholesVanillaEngine,
    FlatForward,
    NullCalendar,
    Period,
    PlainVanillaPayoff,
    QuoteHandle,
    SavedSettings,  # Market handles & helpers
    Settings,
    Simple,
    SimpleQuote,
    YieldTermStructureHandle,
)
from QuantLib import (
    Option as QLOption,  # day count / comp
    VanillaOption as QLVanillaOption,
)

from PricingEngine.Instruments.Common import (
    Option,
    OptionEngineParameters,
)

# ============================================================
# Base equity-style option (no "safe_*", no public process args)
# ============================================================


@dataclass(frozen=True, kw_only=True)
class EquityOption(Option):
    """
    Abstract base for equity options.

    Key conventions:
      - Per-unit results are per 1 underlying unit (matches QL greeks).
      - Scaled/total results use: quantity * contract_size.
      - Public API does NOT accept a 'process' argument; everything uses self._process().
      - Engine greeks are preferred; FD is used ONLY if the engine call raises.
    """

    STYLE: ClassVar[str] = "base"

    # core
    quantity: int
    option_type: int  # QuantLib.Option.Call / Put
    contract_size: int = 100

    # Market inputs (uniform across engines)
    spot: QuoteHandle
    dividend_curve: YieldTermStructureHandle
    risk_free_curve: YieldTermStructureHandle
    vol: BlackVolTermStructureHandle

    # Engine selection (subclasses provide defaults)
    engine_params: OptionEngineParameters

    # Greeks bump style (placeholder hook)
    greek_bump_policy: str = "sticky_strike"  # or "sticky_delta" (not implemented)

    # ------------- validation -------------
    def __post_init__(self) -> None:
        if self.quantity != int(self.quantity) or int(self.quantity) == 0:
            raise ValueError("'quantity' must be a non-zero integer")

        if self.option_type not in (QLOption.Call, QLOption.Put):
            raise ValueError("'option_type' must be Option.Call or Option.Put")

        if int(self.contract_size) <= 0:
            raise ValueError("'contract_size' must be > 0")

        if any(x is None for x in (self.spot, self.dividend_curve, self.risk_free_curve, self.vol)):
            raise ValueError("Missing market inputs: spot/dividend_curve/risk_free_curve/vol")

        # engine validation against style
        self.engine_params.validate_for(self.STYLE)

    def _expiry_date(self) -> Date:  # type: ignore[override]
        raise NotImplementedError

    @cached_property
    def _payoff(self):
        raise NotImplementedError

    @cached_property
    def _exercise(self):
        raise NotImplementedError

    def _engine(self, process: BlackScholesMertonProcess):
        # Subclasses implement mapping to concrete QL engine(s)
        raise NotImplementedError

    def _process(self) -> BlackScholesMertonProcess:
        return BlackScholesMertonProcess(self.spot, self.dividend_curve, self.risk_free_curve, self.vol)

    def _position_multiplier(self) -> float:
        # OPTION convention: per-position = per-unit * quantity * contract_size
        return float(self.quantity) * float(self.contract_size)

    # ------------- finite-difference bump helper -------------
    _EPS_S_REL = 1e-4
    _EPS_SIGMA_REL = 1e-4
    _EPS_R_ABS = 1e-5
    _EPS_T_DAYS = 1  # theta per calendar day

    def _atm_level(self) -> float:
        return float(self.spot.value())

    def _bumped_price(
        self,
        *,
        bump_spot_rel: float | None = None,
        bump_sigma_rel: float | None = None,
        bump_r_abs: float | None = None,
        bump_days: int | None = None,
    ) -> float:
        expiry_date = getattr(self, "maturity", None)
        if expiry_date is None:
            # Bermudan: last exercise date
            expiry_date = self.exercise_dates[-1]

        # ---- spot
        s = self.spot
        if bump_spot_rel is not None:
            s0 = float(self.spot.value())
            s = QuoteHandle(SimpleQuote(s0 * (1.0 + bump_spot_rel)))

        # ---- risk-free (flat curve bumped at the *expiry* tenor)
        r = self.risk_free_curve
        if bump_r_abs is not None:
            vd = self.valuation_date
            dc = self.risk_free_curve.dayCounter() if hasattr(self.risk_free_curve, "dayCounter") else Actual365Fixed()
            lvl = self.risk_free_curve.zeroRate(expiry_date, dc, Simple, Annual).rate()
            r = YieldTermStructureHandle(FlatForward(vd, lvl + bump_r_abs, dc))

        # ---- vol (constant vol bumped using *expiry* tenor)
        v = self.vol
        if bump_sigma_rel is not None:
            dc = self.vol.dayCounter() if hasattr(self.vol, "dayCounter") else Actual365Fixed()
            cal = self.vol.calendar() if hasattr(self.vol, "calendar") else NullCalendar()
            vd = self.valuation_date

            # read the vol at the *expiry* time; stick to strike for now
            sig0 = self.vol.blackVol(expiry_date, self._atm_level())
            if self.greek_bump_policy == "sticky_strike":
                bumped = sig0 * (1.0 + bump_sigma_rel)
            elif self.greek_bump_policy == "sticky_delta":
                # (same as sticky_strike for now; upgrade later if needed)
                bumped = sig0 * (1.0 + bump_sigma_rel)
            else:
                raise ValueError(f"Unknown greek_bump_policy: {self.greek_bump_policy}")

            v = BlackVolTermStructureHandle(BlackConstantVol(vd, cal, max(1e-8, bumped), dc))

        proc = BlackScholesMertonProcess(s, self.dividend_curve, r, v)

        # ---- time bump (theta) if requested
        if bump_days:
            with SavedSettings():
                Settings.instance().evaluationDate = self.valuation_date + Period(f"{int(bump_days)}D")
                option = QLVanillaOption(self._payoff, self._exercise)
                option.setPricingEngine(self._engine(proc))
                return float(option.NPV())

        option = QLVanillaOption(self._payoff, self._exercise)
        option.setPricingEngine(self._engine(proc))
        return float(option.NPV())

    # ------------- engine-or-FD greek wrapper (per unit) -------------
    def _ql_greek(self, name: str) -> float | None:
        if self.is_expired:
            return 0.0

        option = self._ensure_cached_option()

        try:
            val = float(getattr(option, name)())
            self._trace_greek(greek=name, source="engine", engine=self.engine_params.kind, value=val)
            return val
        except Exception:
            return None

    def _trace_greek(self, *, greek: str, source: str, engine: str, value: float):
        # No rebinding; we mutate the deque.
        self._trace.append(
            {
                "greek": greek,
                "source": source,  # "engine" or "fd"
                "engine": engine,  # e.g., "BaroneAdesiWhaleyApproximationEngine"
                "value": float(value),
            }
        )

    def delta(self) -> float:
        g = self._ql_greek("delta")
        if g is not None:
            return g
        eps = self._EPS_S_REL
        up = self._bumped_price(bump_spot_rel=+eps)
        dn = self._bumped_price(bump_spot_rel=-eps)
        s0 = self._atm_level()
        val = (up - dn) / (2.0 * s0 * eps)
        self._trace_greek(greek="delta", source="fd", engine="fd", value=val)
        return val

    def gamma(self) -> float:
        g = self._ql_greek("gamma")
        if g is not None:
            return g
        eps = self._EPS_S_REL
        up = self._bumped_price(bump_spot_rel=+eps)
        mid = self.npv_per_unit()  # use current price as center
        dn = self._bumped_price(bump_spot_rel=-eps)
        s0 = self._atm_level()
        val = (up - 2.0 * mid + dn) / ((s0 * eps) ** 2)
        self._trace_greek(greek="gamma", source="fd", engine="fd", value=val)
        return val

    def vega(self) -> float:
        g = self._ql_greek("vega")
        if g is not None:
            return g
        eps = self._EPS_SIGMA_REL
        up = self._bumped_price(bump_sigma_rel=+eps)
        dn = self._bumped_price(bump_sigma_rel=-eps)
        expiry = self._expiry_date()
        sigma0 = self.vol.blackVol(expiry, self._atm_level())
        val = (up - dn) / (2.0 * sigma0 * eps)
        self._trace_greek(greek="vega", source="fd", engine="fd", value=val)
        return val

    def rho(self) -> float:
        g = self._ql_greek("rho")
        if g is not None:
            return g
        eps = self._EPS_R_ABS
        up = self._bumped_price(bump_r_abs=+eps)
        dn = self._bumped_price(bump_r_abs=-eps)
        val = (up - dn) / (2.0 * eps)
        self._trace_greek(greek="rho", source="fd", engine="fd", value=val)
        return val

    def theta(self) -> float:
        """
        Per-unit theta, *per calendar day* (forward difference).

        Definition:
          theta ≈ [V(t + dt) - V(t)] / dt_days, with dt = 1 day by default.

        Notes:
          - Sign: for most vanilla options, theta <= 0 (time decay).
          - Units: result is per calendar day; use `total_theta()` to include quantity*contract_size.
          - Engines that don't expose theta will fall back to FD on the same process.
        """
        g = self._ql_greek("theta")
        if g is not None:
            return g
        d = self._EPS_T_DAYS
        fwd = self._bumped_price(bump_days=+d)
        now = self.npv_per_unit()
        val = (fwd - now) / d
        self._trace_greek(greek="theta", source="engine", engine="fd", value=val)
        return val

    def calc(
        self,
        *,
        scaled: bool = False,
        include: Iterable[str] = ("price", "delta", "gamma", "vega", "rho", "theta"),
    ) -> dict[str, float]:
        """
        per-unit  = per 1 underlying
        scaled    = per-unit * quantity * contract_size
        """
        out: dict[str, float] = {}
        m = self._position_multiplier() if scaled else 1.0

        if "price" in include:
            out["price"] = self.npv_per_unit() * m

        for gname in ("delta", "gamma", "vega", "rho", "theta"):
            if gname in include:
                per_unit = getattr(self, gname)()
                out[gname] = per_unit * m

        return out


@dataclass(frozen=True, kw_only=True)
class EuropeanVanillaOption(EquityOption):
    STYLE: ClassVar[str] = "european"

    strike: float
    maturity: Date
    engine_params: OptionEngineParameters = field(default_factory=OptionEngineParameters.analytic)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.strike > 0.0):
            raise ValueError("'strike' must be > 0")
        if not isinstance(self.maturity, Date):
            raise TypeError("'maturity' must be a QuantLib Date")

    def _expiry_date(self) -> Date:
        return self.maturity

    @cached_property
    def _payoff(self) -> PlainVanillaPayoff:
        return PlainVanillaPayoff(self.option_type, self.strike)

    @cached_property
    def _exercise(self) -> EuropeanExercise:
        return EuropeanExercise(self.maturity)

    def _engine(self, process: BlackScholesMertonProcess):
        k = self.engine_params.kind
        if self.is_expired or k == "analytic":
            return AnalyticEuropeanEngine(process)
        if k == "fd":
            return FdBlackScholesVanillaEngine(process, int(self.engine_params.nt), int(self.engine_params.nx))
        # Explicit guard: unsupported engines for European
        raise ValueError(f"Engine '{k}' is not supported for European options")


@dataclass(frozen=True, kw_only=True)
class EuropeanDigitalOption(EquityOption):
    STYLE: ClassVar[str] = "euro_digital"

    cash_payoff: float
    strike: float
    maturity: Date
    engine_params: OptionEngineParameters = field(default_factory=OptionEngineParameters.analytic)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.cash_payoff > 0.0):
            raise ValueError("'cash_payoff' must be > 0")
        if not (self.strike > 0.0):
            raise ValueError("'strike' must be > 0")
        if not isinstance(self.maturity, Date):
            raise TypeError("'maturity' must be a QuantLib Date")

    def _expiry_date(self) -> Date:
        return self.maturity

    @cached_property
    def _payoff(self) -> CashOrNothingPayoff:
        return CashOrNothingPayoff(self.option_type, self.strike, self.cash_payoff)

    @cached_property
    def _exercise(self) -> EuropeanExercise:
        return EuropeanExercise(self.maturity)

    def _engine(self, process: BlackScholesMertonProcess):
        k = self.engine_params.kind
        if self.is_expired or k == "analytic":
            # AnalyticEuropeanEngine supports digital payoffs
            return AnalyticEuropeanEngine(process)
        if k == "fd":
            return FdBlackScholesVanillaEngine(process, int(self.engine_params.nt), int(self.engine_params.nx))
        # Explicit guard
        raise ValueError(f"Engine '{k}' is not supported for European Digital options")


@dataclass(frozen=True, kw_only=True)
class AmericanVanillaOption(EquityOption):
    STYLE: ClassVar[str] = "american"

    strike: float
    maturity: Date
    engine_params: OptionEngineParameters = field(default_factory=OptionEngineParameters.baw)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.strike > 0.0):
            raise ValueError("'strike' must be > 0")
        if not isinstance(self.maturity, Date):
            raise TypeError("'maturity' must be a QuantLib Date")

    def _expiry_date(self) -> Date:
        return self.maturity

    @cached_property
    def _payoff(self) -> PlainVanillaPayoff:
        return PlainVanillaPayoff(self.option_type, self.strike)

    @cached_property
    def _exercise(self) -> AmericanExercise:
        vd = self.valuation_date
        last = self.maturity
        earliest = vd if vd <= last else last
        return AmericanExercise(earliest, last)

    def _engine(self, process: BlackScholesMertonProcess):
        k = self.engine_params.kind
        if self.is_expired or k == "baw":
            return BaroneAdesiWhaleyApproximationEngine(process)
        if k == "bjerksund":
            return BjerksundStenslandApproximationEngine(process)
        if k == "fd":
            return FdBlackScholesVanillaEngine(process, int(self.engine_params.nt), int(self.engine_params.nx))
        if k == "tree":
            tag = self.engine_params.tree_tag()
            return BinomialVanillaEngine(process, tag, int(self.engine_params.steps))
        # Explicit guard
        raise ValueError(f"Engine '{k}' is not supported for AmericanVanillaOption")


@dataclass(frozen=True, kw_only=True)
class BermudanVanillaOption(EquityOption):
    STYLE: ClassVar[str] = "bermudan"

    strike: float
    exercise_dates: tuple[Date, ...]
    engine_params: OptionEngineParameters = field(
        default_factory=lambda: OptionEngineParameters.tree(method="lr", steps=801)
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.strike > 0.0):
            raise ValueError("'strike' must be > 0")
        if not self.exercise_dates:
            raise ValueError("'exercise_dates' must be a non-empty tuple of Date")
        # sort & dedup (frozen dataclass → set via object.__setattr__)
        ed = tuple(sorted(set(self.exercise_dates)))
        object.__setattr__(self, "exercise_dates", ed)

    def _expiry_date(self) -> Date:
        return self.exercise_dates[-1]

    @property
    def is_expired(self) -> bool:
        return Settings.instance().evaluationDate > self.exercise_dates[-1]

    @cached_property
    def _payoff(self) -> PlainVanillaPayoff:
        return PlainVanillaPayoff(self.option_type, self.strike)

    @cached_property
    def _exercise(self) -> BermudanExercise:
        return BermudanExercise(list(self.exercise_dates))

    def _engine(self, process: BlackScholesMertonProcess):
        k = self.engine_params.kind
        if self.is_expired:
            tag = self.engine_params.tree_tag(default="LR")
            return BinomialVanillaEngine(process, tag, max(3, int(self.engine_params.steps or 801)))
        if k == "fd":
            return FdBlackScholesVanillaEngine(process, int(self.engine_params.nt), int(self.engine_params.nx))
        if k == "tree":
            tag = self.engine_params.tree_tag()
            return BinomialVanillaEngine(process, tag, int(self.engine_params.steps))

        # Explicit guard
        raise ValueError(f"Engine '{k}' is not supported for BermudanVanillaOption")
