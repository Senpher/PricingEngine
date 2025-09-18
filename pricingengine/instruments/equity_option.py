from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from QuantLib import (
    TARGET,
    Actual365Fixed,
    AnalyticEuropeanEngine,
    BlackConstantVol,
    BlackScholesMertonProcess,
    BlackVolTermStructureHandle,
    Date,
    EuropeanExercise,
    FlatForward,
    Option,
    PlainVanillaPayoff,
    QuoteHandle,
    Settings,
    SimpleQuote,
    VanillaOption,
    YieldTermStructureHandle,
)

from pricingengine.instruments._instrument import Instrument

try:  # Optional engines depending on QuantLib build
    from QuantLib import BaroneAdesiWhaleyEngine
except ImportError:  # pragma: no cover - optional dependency
    BaroneAdesiWhaleyEngine = None  # type: ignore[assignment]

try:
    from QuantLib import BinomialVanillaEngine
except ImportError:  # pragma: no cover - optional dependency
    BinomialVanillaEngine = None  # type: ignore[assignment]

try:
    from QuantLib import BjerksundStenslandEngine
except ImportError:  # pragma: no cover - optional dependency
    BjerksundStenslandEngine = None  # type: ignore[assignment]

try:
    from QuantLib import FdBlackScholesVanillaEngine
except ImportError:  # pragma: no cover - optional dependency
    FdBlackScholesVanillaEngine = None  # type: ignore[assignment]

_ENGINE_ALIASES: dict[str, str] = {
    "analytic": "analytic",
    "black": "analytic",
    "analytic_european": "analytic",
    "barone_adesi_whaley": "barone_adesi_whaley",
    "barone-adesi-whaley": "barone_adesi_whaley",
    "baw": "barone_adesi_whaley",
    "bjerksund_stensland": "bjerksund_stensland",
    "bjerksund-stensland": "bjerksund_stensland",
    "bs": "bjerksund_stensland",
    "fd": "finite_difference",
    "fdm": "finite_difference",
    "finite_difference": "finite_difference",
    "finite-difference": "finite_difference",
    "binomial": "binomial",
    "tree": "binomial",
}

_BINOMIAL_TREE_ALIASES: dict[str, str] = {
    "jr": "JR",
    "jarrow-rudd": "JR",
    "crr": "CRR",
    "cox-ross-rubinstein": "CRR",
    "eqp": "EQP",
    "trigeorgis": "Trigeorgis",
    "tian": "Tian",
    "lr": "LR",
    "joshi4": "Joshi4",
}


@dataclass(frozen=True, kw_only=True)
class EquityOption(Instrument):
    """Vanilla European equity option backed by QuantLib handles."""

    maturity: Date
    option_type: str
    strike: float
    spot: QuoteHandle | Any
    discount_curve: YieldTermStructureHandle | Any
    volatility: BlackVolTermStructureHandle | Any
    dividend_curve: YieldTermStructureHandle | Any | None = None
    calendar: Any | None = None
    day_counter: Any | None = None
    engine: str = "analytic"
    time_steps: int = 200
    grid_points: int = 200
    binomial_tree: str = "jr"

    _spot_handle: QuoteHandle = field(init=False, repr=False)
    _discount_curve_handle: YieldTermStructureHandle = field(init=False, repr=False)
    _dividend_curve_handle: YieldTermStructureHandle = field(init=False, repr=False)
    _vol_surface_handle: BlackVolTermStructureHandle = field(init=False, repr=False)
    _ql_option_type: int = field(init=False, repr=False)
    _payoff: PlainVanillaPayoff = field(init=False, repr=False)
    _exercise: EuropeanExercise = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "calendar", self.calendar or TARGET())
        object.__setattr__(self, "day_counter", self.day_counter or Actual365Fixed())

        if not isinstance(self.maturity, Date):
            raise TypeError("maturity must be a QuantLib Date instance")

        strike = float(self.strike)
        if strike <= 0.0:
            raise ValueError("strike must be strictly positive")
        object.__setattr__(self, "strike", strike)

        canonical_type = self.option_type.lower()
        if canonical_type not in {"call", "put"}:
            raise ValueError("option_type must be 'call' or 'put'")
        object.__setattr__(self, "option_type", canonical_type)
        object.__setattr__(self, "_ql_option_type", Option.Call if canonical_type == "call" else Option.Put)

        resolved_engine = self._resolve_engine_name(self.engine)
        object.__setattr__(self, "engine", resolved_engine)

        resolved_tree = self._resolve_tree_label(self.binomial_tree)
        object.__setattr__(self, "binomial_tree", resolved_tree)

        time_steps = int(self.time_steps)
        grid_points = int(self.grid_points)
        if time_steps <= 0:
            raise ValueError("time_steps must be a positive integer")
        if grid_points <= 0:
            raise ValueError("grid_points must be a positive integer")
        object.__setattr__(self, "time_steps", time_steps)
        object.__setattr__(self, "grid_points", grid_points)

        spot_handle = self._coerce_quote_handle(self.spot, "spot")
        discount_handle = self._coerce_yield_curve(self.discount_curve, "discount_curve")
        dividend_handle = self._coerce_yield_curve(self.dividend_curve, "dividend_curve", allow_none=True, default=0.0)
        vol_handle = self._coerce_volatility(self.volatility, "volatility")

        object.__setattr__(self, "_spot_handle", spot_handle)
        object.__setattr__(self, "_discount_curve_handle", discount_handle)
        object.__setattr__(self, "_dividend_curve_handle", dividend_handle)
        object.__setattr__(self, "_vol_surface_handle", vol_handle)

        payoff = PlainVanillaPayoff(self._ql_option_type, strike)
        exercise = EuropeanExercise(self.maturity)
        object.__setattr__(self, "_payoff", payoff)
        object.__setattr__(self, "_exercise", exercise)

    # ---------- properties ----------
    @property
    def valuation_date(self) -> Date:
        return Settings.instance().evaluationDate

    @property
    def is_expired(self) -> bool:
        return self.valuation_date >= self.maturity

    @property
    def spot_handle(self) -> QuoteHandle:
        return self._spot_handle

    @property
    def discount_curve_handle(self) -> YieldTermStructureHandle:
        return self._discount_curve_handle

    @property
    def dividend_curve_handle(self) -> YieldTermStructureHandle:
        return self._dividend_curve_handle

    @property
    def volatility_handle(self) -> BlackVolTermStructureHandle:
        return self._vol_surface_handle

    # ---------- helpers ----------
    @staticmethod
    def _resolve_engine_name(name: str) -> str:
        try:
            return _ENGINE_ALIASES[name.lower()]
        except (AttributeError, KeyError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported engine '{name}'.") from exc

    @staticmethod
    def _resolve_tree_label(name: str) -> str:
        try:
            return _BINOMIAL_TREE_ALIASES[name.lower()]
        except (AttributeError, KeyError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported binomial tree '{name}'.") from exc

    def _coerce_quote_handle(self, value: QuoteHandle | Any, name: str) -> QuoteHandle:
        if isinstance(value, QuoteHandle):
            return value
        if hasattr(value, "value") and callable(value.value):
            return QuoteHandle(value)
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError(f"{name} must be a QuoteHandle or numeric value") from exc
        return QuoteHandle(SimpleQuote(numeric))

    def _coerce_yield_curve(
        self,
        value: YieldTermStructureHandle | Any | None,
        name: str,
        *,
        allow_none: bool = False,
        default: float | None = None,
    ) -> YieldTermStructureHandle:
        if isinstance(value, YieldTermStructureHandle):
            return value
        if value is None:
            if not allow_none:
                raise TypeError(f"{name} must be provided")
            rate = 0.0 if default is None else float(default)
            curve = FlatForward(self.valuation_date, rate, self.day_counter)
            return YieldTermStructureHandle(curve)
        if hasattr(value, "discount") and callable(value.discount):
            return YieldTermStructureHandle(value)
        try:
            rate = float(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError(f"{name} must be a YieldTermStructureHandle or numeric value") from exc
        curve = FlatForward(self.valuation_date, rate, self.day_counter)
        return YieldTermStructureHandle(curve)

    def _coerce_volatility(self, value: BlackVolTermStructureHandle | Any, name: str) -> BlackVolTermStructureHandle:
        if isinstance(value, BlackVolTermStructureHandle):
            return value
        if hasattr(value, "blackVol") and callable(value.blackVol):
            return BlackVolTermStructureHandle(value)
        try:
            vol = float(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError(f"{name} must be a BlackVolTermStructureHandle or numeric value") from exc
        if vol < 0.0:
            raise ValueError("volatility must be non-negative")
        surface = BlackConstantVol(self.valuation_date, self.calendar, vol, self.day_counter)
        return BlackVolTermStructureHandle(surface)

    def _process(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
    ) -> BlackScholesMertonProcess:
        s_handle = self._coerce_quote_handle(spot, "spot") if spot is not None else self._spot_handle
        v_handle = (
            self._coerce_volatility(volatility, "volatility") if volatility is not None else self._vol_surface_handle
        )
        r_handle = (
            self._coerce_yield_curve(discount_curve, "discount_curve")
            if discount_curve is not None
            else self._discount_curve_handle
        )
        q_handle = (
            self._coerce_yield_curve(dividend_curve, "dividend_curve", allow_none=True, default=0.0)
            if dividend_curve is not None
            else self._dividend_curve_handle
        )
        return BlackScholesMertonProcess(s_handle, q_handle, r_handle, v_handle)

    def _engine(self, process: BlackScholesMertonProcess, engine: str | None = None):
        resolved = self._resolve_engine_name(engine or self.engine)
        if resolved == "analytic":
            return AnalyticEuropeanEngine(process)
        if resolved == "barone_adesi_whaley":
            if BaroneAdesiWhaleyEngine is None:
                msg = "Barone-Adesi-Whaley engine is unavailable in this QuantLib build"
                raise RuntimeError(msg)
            return BaroneAdesiWhaleyEngine(process)
        if resolved == "bjerksund_stensland":
            if BjerksundStenslandEngine is None:
                msg = "Bjerksund-Stensland engine is unavailable in this QuantLib build"
                raise RuntimeError(msg)
            return BjerksundStenslandEngine(process)
        if resolved == "finite_difference":
            if FdBlackScholesVanillaEngine is None:
                msg = "Finite-difference engine is unavailable in this QuantLib build"
                raise RuntimeError(msg)
            return FdBlackScholesVanillaEngine(process, self.time_steps, self.grid_points)
        if resolved == "binomial":
            if BinomialVanillaEngine is None:
                msg = "Binomial engine is unavailable in this QuantLib build"
                raise RuntimeError(msg)
            return BinomialVanillaEngine(process, self.binomial_tree, self.time_steps)
        raise ValueError(f"Unsupported engine '{engine}'.")  # pragma: no cover - defensive

    def _option(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> VanillaOption:
        process = self._process(
            spot=spot,
            volatility=volatility,
            discount_curve=discount_curve,
            dividend_curve=dividend_curve,
        )
        option = VanillaOption(self._payoff, self._exercise)
        option.setPricingEngine(self._engine(process, engine))
        return option

    # ---------- analytics ----------
    def mark_to_market(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        npv = self._option(
            spot=spot,
            volatility=volatility,
            discount_curve=discount_curve,
            dividend_curve=dividend_curve,
            engine=engine,
        ).NPV()
        return float(npv)

    def delta(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).delta()
        )

    def gamma(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).gamma()
        )

    def vega(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).vega()
        )

    def theta(
        self,
        *,
        per_day: bool = False,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        opt = self._option(
            spot=spot,
            volatility=volatility,
            discount_curve=discount_curve,
            dividend_curve=dividend_curve,
            engine=engine,
        )
        return float(opt.thetaPerDay() if per_day else opt.theta())

    def rho(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).rho()
        )

    def dividend_rho(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).dividendRho()
        )

    def elasticity(
        self,
        *,
        spot: QuoteHandle | Any | None = None,
        volatility: BlackVolTermStructureHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        engine: str | None = None,
    ) -> float:
        if self.is_expired:
            return 0.0
        return float(
            self._option(
                spot=spot,
                volatility=volatility,
                discount_curve=discount_curve,
                dividend_curve=dividend_curve,
                engine=engine,
            ).elasticity()
        )

    def implied_volatility(
        self,
        target_price: float,
        *,
        spot: QuoteHandle | Any | None = None,
        discount_curve: YieldTermStructureHandle | Any | None = None,
        dividend_curve: YieldTermStructureHandle | Any | None = None,
        accuracy: float = 1e-7,
        max_evaluations: int = 500,
        min_vol: float = 1e-6,
        max_vol: float = 5.0,
    ) -> float:
        if self.is_expired:
            return 0.0
        process = self._process(
            spot=spot,
            discount_curve=discount_curve,
            dividend_curve=dividend_curve,
        )
        option = VanillaOption(self._payoff, self._exercise)
        vol = option.impliedVolatility(
            float(target_price),
            process,
            float(accuracy),
            int(max_evaluations),
            float(min_vol),
            float(max_vol),
        )
        return float(vol)

    # ---------- diagnostics ----------
    def forward_price(self) -> float:
        spot = float(self._spot_handle.value())
        disc = float(self._discount_curve_handle.discount(self.maturity))
        div = float(self._dividend_curve_handle.discount(self.maturity))
        return spot * div / disc

    def intrinsic_value(self) -> float:
        return float(self._payoff(self._spot_handle.value()))

    def time_value(self) -> float:
        return max(0.0, self.mark_to_market() - self.intrinsic_value())

    def vanilla_option(self, **kwargs) -> VanillaOption:
        """Expose the configured QuantLib VanillaOption for advanced users."""
        return self._option(**kwargs)
