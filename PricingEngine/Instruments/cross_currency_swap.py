from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from QuantLib import (
    Actual365Fixed,
    Calendar,
    CashFlows,
    Date,
    DayCounter,
    Days,
    FxSwapRateHelper,
    JointCalendar,
    ModifiedFollowing,
    Period,
    PiecewiseLogLinearDiscount,
    QuoteHandle,
    Settings,
    SimpleQuote,
    YieldTermStructureHandle,
)

from PricingEngine.Instruments.Common import Instrument, SwapLeg


@dataclass(frozen=True, kw_only=True)
class CrossCurrencySwap(Instrument):
    """Cross-currency swap valued off discount curves and FX forwards."""

    paying_leg: SwapLeg
    receiving_leg: SwapLeg
    discount_curves: Mapping[str, YieldTermStructureHandle]
    fx_spot: QuoteHandle
    fx_forward_points: Sequence[Mapping[str, Any]]

    collateral_currency: str | None = None
    pricing_currency: str | None = None
    base_currency_is_collateral: bool | None = None

    fx_fixing_days: int = 2
    fx_calendar: Calendar | None = None
    fx_convention: int = ModifiedFollowing
    fx_end_of_month: bool = False
    fx_day_counter: DayCounter = field(default_factory=Actual365Fixed)

    exchange_initial_notional: bool = True
    exchange_final_notional: bool = True

    foreign_currency: str = field(init=False, repr=False)

    def __post_init__(self):
        self._validate_legs()

        pricing_ccy, collateral_ccy, foreign_ccy = self._resolve_currencies()
        object.__setattr__(self, "pricing_currency", pricing_ccy)
        object.__setattr__(self, "collateral_currency", collateral_ccy)
        object.__setattr__(self, "foreign_currency", foreign_ccy)

        fx_calendar = self.fx_calendar or JointCalendar(self.paying_leg.calendar, self.receiving_leg.calendar)
        object.__setattr__(self, "fx_calendar", fx_calendar)

        self._ensure_positive_spot()
        points = self._normalise_fx_points()
        object.__setattr__(self, "fx_forward_points", points)

        curves = self._prepare_discount_curves(pricing_ccy, collateral_ccy, foreign_ccy)
        object.__setattr__(self, "discount_curves", curves)

    # ---------- validation & setup ----------
    def _validate_legs(self) -> None:
        if not isinstance(self.paying_leg, SwapLeg) or not isinstance(self.receiving_leg, SwapLeg):
            raise ValueError("'paying_leg' and 'receiving_leg' must be instances of SwapLeg")
        if self.paying_leg.currency == self.receiving_leg.currency:
            raise ValueError("Cross-currency swap legs must use different currencies")
        if self.paying_leg.valuation_date != self.receiving_leg.valuation_date:
            raise ValueError("Both legs must share the same valuation date")
        if self.paying_leg.issue_date != self.receiving_leg.issue_date:
            raise ValueError("Both legs must share the same issue date")
        if self.paying_leg.maturity != self.receiving_leg.maturity:
            raise ValueError("Both legs must share the same maturity")

    def _resolve_currencies(self) -> tuple[str, str, str]:
        pricing_ccy = self.receiving_leg.currency if self.pricing_currency is None else self.pricing_currency
        if pricing_ccy not in {self.paying_leg.currency, self.receiving_leg.currency}:
            raise ValueError("pricing_currency must match one of the swap legs")
        collateral_ccy = pricing_ccy if self.collateral_currency is None else self.collateral_currency
        foreign_ccy = (
            self.paying_leg.currency if pricing_ccy == self.receiving_leg.currency else self.receiving_leg.currency
        )
        return pricing_ccy, collateral_ccy, foreign_ccy

    def _ensure_positive_spot(self) -> float:
        try:
            spot = float(self.fx_spot.value())
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("fx_spot must contain a valid quote") from exc
        if spot <= 0.0:
            raise ValueError("fx_spot must contain a positive value")
        return spot

    def _normalise_fx_points(self) -> tuple[tuple[Period, float], ...]:
        if not self.fx_forward_points:
            raise ValueError("fx_forward_points must contain at least one tenor/points entry")
        cleaned: list[tuple[Period, float]] = []
        for item in self.fx_forward_points:
            if not isinstance(item, Mapping):
                raise ValueError("fx_forward_points entries must be mappings with 'tenor' and 'points'")
            if "tenor" not in item or "points" not in item:
                raise ValueError("fx_forward_points entries must provide 'tenor' and 'points'")
            tenor = self._to_period(item["tenor"])
            pts = float(item["points"])
            cleaned.append((tenor, pts))
        cleaned.sort(key=lambda x: (x[0].length(), x[0].units()))
        return tuple(cleaned)

    def _prepare_discount_curves(
        self, pricing_ccy: str, collateral_ccy: str, foreign_ccy: str
    ) -> dict[str, YieldTermStructureHandle]:
        curves: dict[str, YieldTermStructureHandle] = {}
        for code, handle in self.discount_curves.items():
            if not isinstance(code, str):
                raise ValueError("discount_curves keys must be currency codes")
            if not isinstance(handle, YieldTermStructureHandle):
                raise ValueError("discount_curves values must be YieldTermStructureHandle instances")
            self._ensure_handle_ok(handle, f"discount curve for {code}", self.maturity)
            curves[code] = handle

        if pricing_ccy not in curves:
            raise ValueError(f"Missing discount curve for pricing currency '{pricing_ccy}'")
        if collateral_ccy not in curves:
            raise ValueError(f"Missing discount curve for collateral currency '{collateral_ccy}'")

        base_is_collateral = (
            self.base_currency_is_collateral
            if self.base_currency_is_collateral is not None
            else foreign_ccy == collateral_ccy
        )
        object.__setattr__(self, "base_currency_is_collateral", base_is_collateral)

        if foreign_ccy not in curves:
            foreign_curve = self._build_foreign_curve(
                collateral_curve=curves[collateral_ccy],
                base_is_collateral=base_is_collateral,
            )
            self._ensure_handle_ok(foreign_curve, f"bootstrapped curve for {foreign_ccy}", self.maturity)
            curves[foreign_ccy] = foreign_curve

        return curves

    def _discount_amount(self, amount: float, date: Date, handle: YieldTermStructureHandle) -> float:
        if date < self.valuation_date:
            return 0.0
        return amount * float(handle.discount(date))

    # ---------- timeline ----------
    @property
    def valuation_date(self) -> Date:
        return Settings.instance().evaluationDate

    @property
    def issue_date(self) -> Date:
        return self.paying_leg.issue_date

    @property
    def maturity(self) -> Date:
        return self.paying_leg.maturity

    @property
    def is_expired(self) -> bool:
        return self.valuation_date > self.maturity

    @cached_property
    def joint_calendar(self) -> Calendar:
        return JointCalendar(self.paying_leg.calendar, self.receiving_leg.calendar)

    # ---------- helpers ----------
    @staticmethod
    def _to_period(value: Any) -> Period:
        if isinstance(value, Period):
            return value
        if isinstance(value, str):
            return Period(value)
        raise ValueError(f"Unsupported tenor format: {value!r}")

    @staticmethod
    def _ensure_handle_ok(handle: YieldTermStructureHandle, name: str, horizon: Date) -> None:
        try:
            ts = handle.currentLink()
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"{name} is not a valid YieldTermStructureHandle") from exc
        ref = ts.referenceDate()
        max_date = ts.maxDate()
        if (horizon < ref or horizon > max_date) and not ts.allowsExtrapolation():
            raise ValueError(
                f"{name} cannot be used at {horizon.ISO()} (ref={ref.ISO()}, max={max_date.ISO()}, extrapolation disabled)"
            )
        if horizon >= ref:
            _ = float(ts.discount(horizon))

    def _build_foreign_curve(
        self, *, collateral_curve: YieldTermStructureHandle, base_is_collateral: bool
    ) -> YieldTermStructureHandle:
        helpers: list[FxSwapRateHelper] = []
        for tenor, points in self.fx_forward_points:
            helpers.append(
                FxSwapRateHelper(
                    QuoteHandle(SimpleQuote(points)),
                    self.fx_spot,
                    tenor,
                    self.fx_fixing_days,
                    self.fx_calendar,
                    self.fx_convention,
                    self.fx_end_of_month,
                    base_is_collateral,
                    collateral_curve,
                    self.fx_calendar,
                )
            )

        eval_date = Settings.instance().evaluationDate
        curve = PiecewiseLogLinearDiscount(eval_date, helpers, self.fx_day_counter)
        curve.enableExtrapolation()
        return YieldTermStructureHandle(curve)

    def _conversion_factor_for(self, currency: str) -> float:
        if currency == self.pricing_currency:
            return 1.0
        if currency == self.foreign_currency:
            return self._spot_conversion_factor
        raise ValueError(f"No conversion available for currency {currency!r}")

    @cached_property
    def _spot_conversion_factor(self) -> float:
        pricing_curve = self.discount_curves[self.pricing_currency]
        foreign_curve = self.discount_curves[self.foreign_currency]
        spot_date = self.fx_calendar.advance(
            self.valuation_date,
            Period(self.fx_fixing_days, Days),
            self.fx_convention,
            self.fx_end_of_month,
        )

        df_pricing_spot = float(pricing_curve.discount(spot_date))
        df_foreign_spot = float(foreign_curve.discount(spot_date))
        if df_pricing_spot <= 0.0 or df_foreign_spot <= 0.0:
            raise ValueError("Spot-date discount factors must be positive")
        return float(self.fx_spot.value()) * df_pricing_spot / df_foreign_spot

    def _leg_pv_local(self, leg: SwapLeg) -> float:
        handle = self.discount_curves[leg.currency]
        sign = 1.0 if leg is self.receiving_leg else -1.0
        pv = sign * CashFlows.npv(leg.cashflows, handle, False, self.valuation_date)

        schedule_dates = list(leg.schedule.dates())
        nominals = leg.nominals
        if self.exchange_initial_notional and schedule_dates:
            initial = nominals[0]
            if initial != 0:
                pv += self._discount_amount(sign * initial, schedule_dates[0], handle)
        if self.exchange_final_notional and schedule_dates:
            final = nominals[-1]
            if final != 0:
                pv += self._discount_amount(-sign * final, schedule_dates[-1], handle)
        return pv

    # ---------- analytics ----------
    def npv(self, *, breakdown: bool = False) -> float | dict[str, Any]:
        if self.is_expired:
            return 0.0 if not breakdown else {"npv": 0.0, "pricing_currency": self.pricing_currency, "legs": {}}

        pv_rec_local = self._leg_pv_local(self.receiving_leg)
        pv_pay_local = self._leg_pv_local(self.paying_leg)

        pv_rec_pricing = pv_rec_local * self._conversion_factor_for(self.receiving_leg.currency)
        pv_pay_pricing = pv_pay_local * self._conversion_factor_for(self.paying_leg.currency)

        total = pv_rec_pricing + pv_pay_pricing

        if not breakdown:
            return total

        return {
            "npv": total,
            "pricing_currency": self.pricing_currency,
            "legs": {
                "receiving": {
                    "currency": self.receiving_leg.currency,
                    "pv_local": pv_rec_local,
                    "pv_pricing": pv_rec_pricing,
                },
                "paying": {
                    "currency": self.paying_leg.currency,
                    "pv_local": pv_pay_local,
                    "pv_pricing": pv_pay_pricing,
                },
            },
            "fx": {
                "spot": float(self.fx_spot.value()),
                "conversion_factor": self._spot_conversion_factor,
                "pricing_currency": self.pricing_currency,
                "foreign_currency": self.foreign_currency,
            },
        }
