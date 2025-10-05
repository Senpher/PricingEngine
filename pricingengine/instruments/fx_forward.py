from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Dict, Any

from QuantLib import (
    Date,
    Settings,
    YieldTermStructureHandle,
    QuoteHandle,
    FxSwapRateHelper,
    SimpleQuote,
    PiecewiseLogLinearDiscount,
    Period,
    Days,
    Years,
    Months,
    Weeks,
    DayCounter,
    Actual365Fixed,
    ModifiedFollowing,
    Calendar,
    TARGET,
)

from pricingengine.currencies import CURRENCIES
from pricingengine.instruments._instrument import Instrument


@dataclass(frozen=True, kw_only=True)
class FxForward(Instrument):
    """
    FX Forward priced from spot + FX swap *points* via FxSwapRateHelper(s).
    The class bootstraps the implied foreign (BASE) discount curve internally.

    Conventions:
      - spot is PRICE/BASE = domestic/foreign (e.g., USD per EUR).
      - fx_fwd_pts_curve: list of dicts like {'tenor': '6M', 'points': 0.00310}.
        'points' must be in the SAME direction as spot (PRICE terms), i.e. F - S.
      - PV currency = PRICE currency.

    PV (long BASE / short PRICE):
        NPV = sign * N * DF_domestic(T) * ( F(T) - K )

      where:
        sign = +1 if long_base else -1
        N    = nominal in BASE units
        F(T) = S * DF_foreign(T) / DF_domestic(T)
        DF_domestic(T) = discount_domestic.discount(T)
        K    = contracted forward (PRICE/BASE)
    """

    # ------- contract terms -------
    nominal: float
    forward_price: float  # K (PRICE per 1 BASE)
    maturity: Date
    base_currency: str
    price_currency: str
    long_base: bool = True

    # ------- market data inputs -------
    spot: QuoteHandle  # PRICE/BASE
    discount_domestic: YieldTermStructureHandle  # PRICE-currency (CSA) discount curve
    fx_fwd_pts_curve: List[Dict[str, Any]]  # [{'tenor': '6M', 'points': 0.00310}, ...]

    # ------- market conventions (you can override per trade) -------
    calendar: Calendar = TARGET()
    fixing_days: int = 2
    convention: int = ModifiedFollowing
    end_of_month: bool = False
    base_currency_is_collateral: bool = False
    day_counter: DayCounter = Actual365Fixed()

    # ------- built internally (frozen dataclass -> set via object.__setattr__) -------
    discount_foreign: YieldTermStructureHandle | None = None  # implied BASE curve

    # ---------- lifecycle / validation ----------
    def __post_init__(self):
        # basic checks
        if self.nominal <= 0:
            raise ValueError("'nominal' must be positive")
        if self.forward_price <= 0:
            raise ValueError("'forward_price' must be positive")
        if (
            self.base_currency not in CURRENCIES
            or self.price_currency not in CURRENCIES
        ):
            raise ValueError("Unknown currency code(s)")
        if self.base_currency == self.price_currency:
            raise ValueError("Base and price currencies must differ")

        # spot sanity
        try:
            s = float(self.spot.value())
        except Exception as e:
            raise ValueError("spot (QuoteHandle) is not set or invalid") from e
        if s <= 0.0:
            raise ValueError("spot must be positive")

        # domestic curve usable at maturity
        self._ensure_handle_ok(
            self.discount_domestic, "discount_domestic", self.maturity
        )

        # need at least one point
        if not self.fx_fwd_pts_curve:
            raise ValueError("fx_fwd_pts_curve must contain at least one item")

        # --- build the foreign (BASE) curve from the list[dict] of points
        foreign = self._build_foreign_curve_from_points()
        # ensure usable at maturity and store
        self._ensure_handle_ok(foreign, "bootstrapped_foreign", self.maturity)
        object.__setattr__(self, "discount_foreign", foreign)

    # ---------- static helpers ----------
    @staticmethod
    def _to_period(x: Any) -> Period:
        if isinstance(x, Period):
            return x
        if isinstance(x, str):
            s = x.strip().upper()
            if s.endswith("W"):
                return Period(int(s[:-1]), Weeks)
            if s.endswith("M"):
                return Period(int(s[:-1]), Months)
            if s.endswith("Y"):
                return Period(int(s[:-1]), Years)
            if s.endswith("D"):
                return Period(int(s[:-1]), Days)
        raise ValueError(f"Unsupported tenor format: {x!r}")

    @staticmethod
    def _ensure_handle_ok(h: YieldTermStructureHandle, name: str, d: Date) -> None:
        try:
            ts = h.currentLink()
        except Exception as e:
            raise ValueError(f"{name} is not a valid YieldTermStructureHandle") from e
        ref = ts.referenceDate()
        max_d = ts.maxDate()
        if (d < ref or d > max_d) and not ts.allowsExtrapolation():
            raise ValueError(
                f"{name} cannot be used at {d.ISO()} "
                f"(ref={ref.ISO()}, max={max_d.ISO()}, extrapolation disabled)"
            )
        if d >= ref:
            _ = float(ts.discount(d))  # probe only when time >= 0

    def _build_foreign_curve_from_points(self) -> YieldTermStructureHandle:
        """
        Build BASE-currency discount curve from FX swap points using FxSwapRateHelper.
        """
        helpers: list[FxSwapRateHelper] = []
        for item in self.fx_fwd_pts_curve:
            if "tenor" not in item or "points" not in item:
                raise ValueError(
                    f"fx_fwd_pts_curve item must have 'tenor' and 'points': {item!r}"
                )
            tenor = self._to_period(item["tenor"])
            pts = float(item["points"])
            qh = QuoteHandle(SimpleQuote(pts))
            helpers.append(
                FxSwapRateHelper(
                    qh,
                    self.spot,
                    tenor,
                    self.fixing_days,
                    self.calendar,
                    self.convention,
                    self.end_of_month,
                    self.base_currency_is_collateral,
                    self.discount_domestic,
                )
            )

        eval_date = Settings.instance().evaluationDate
        link = PiecewiseLogLinearDiscount(eval_date, helpers, self.day_counter)
        link.enableExtrapolation()
        return YieldTermStructureHandle(link)

    # ---------- timeline ----------
    @property
    def valuation_date(self) -> Date:
        return Settings.instance().evaluationDate

    @property
    def is_expired(self) -> bool:
        return self.valuation_date > self.maturity  # not expired on maturity date

    # ---------- analytics ----------
    def fair_forward(self) -> float:
        """
        Outright forward F(T) via CIP, *spot-normalised*.

        FX forwards are quoted for delivery from SPOT (T+2) to FAR.
        The helpers were set up with SPOT→FAR, while our curve handles are ASOF→date.
        So we include the spot normalisation factor DF_d(ASOF→SPOT)/DF_f(ASOF→SPOT).
        """
        s = float(self.spot.value())
        far = self.maturity

        # SPOT date using same conventions as the helpers
        spot_date = self.calendar.advance(
            self.valuation_date,
            Period(self.fixing_days, Days),
            self.convention,
            self.end_of_month,
        )

        # ASOF→... discounts
        df_d_far = float(self.discount_domestic.discount(far))
        df_f_far = float(self.discount_foreign.discount(far))
        df_d_spot = float(self.discount_domestic.discount(spot_date))
        df_f_spot = float(self.discount_foreign.discount(spot_date))

        if min(df_d_far, df_f_far, df_d_spot, df_f_spot) <= 0.0:
            raise ValueError("discount factors must be positive")

        # Spot-normalised CIP
        return s * (df_f_far / df_d_far) * (df_d_spot / df_f_spot)

    def npv(self, *, breakdown: bool = False) -> float | dict:
        if self.is_expired:
            return (
                0.0
                if not breakdown
                else {
                    "npv": 0.0,
                    "discount_factor": 1.0,
                    "market_forward": None,
                    "strike": self.forward_price,
                    "notional": self.nominal,
                    "base_currency": self.base_currency,
                    "price_currency": self.price_currency,
                }
            )

        df_dom = float(self.discount_domestic.discount(self.maturity))
        f_mkt = self.fair_forward()
        sign = 1.0 if self.long_base else -1.0
        pv = sign * self.nominal * df_dom * (f_mkt - self.forward_price)

        if breakdown:
            return {
                "npv": pv,
                "discount_factor": df_dom,
                "market_forward": f_mkt,
                "strike": self.forward_price,
                "notional": self.nominal,
                "base_currency": self.base_currency,
                "price_currency": self.price_currency,
            }
        return pv

    # Back-compat alias
    def mark_to_market(self, *, breakdown: bool = False) -> float | dict:
        return self.npv(breakdown=breakdown)

    # convenience "setter"
    def with_forward(self, forward_price: float) -> "FxForward":
        if forward_price <= 0:
            raise ValueError("'forward_price' must be positive")
        return replace(self, forward_price=forward_price)
