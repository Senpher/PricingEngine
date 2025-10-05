from __future__ import annotations

from datetime import date

import numpy as np
from QuantLib import (
    TARGET,
    Actual360,
    Date,
    Period,
    YieldTermStructureHandle,
    as_floating_rate_coupon,
)

from pricingengine.cashflows.swap_leg import FixedLeg, FloatingLeg
from pricingengine.instruments.interest_rate_swap import InterestRateSwap

from ..data_structures.market_data_mapper import MarketDataMapper
from ..data_structures.QL_Mapping import (
    QL_day_count_mapper,
    QL_swap_leg_mapper,
    generic_ibor,
    ql_eval_date,
)
from .client_positions import ClientPosition


class IRS(ClientPosition):
    """
    Portfolio engine wrapper around pricingengine.InterestRateSwap.

    - Uses QuantLib global Settings.evaluationDate via ql_eval_date().
    - Builds legs using pricingengine swap-leg classes (via QL_swap_leg_mapper).
    - Builds discounting handle and a forecasting IborIndex from provided curve dicts.
    - Binds the real index onto the floating leg (via with_index) before pricing.
    - Exposes `self.swap` so valuePosition() can simply return self.swap.mark_to_market().
    """

    def __init__(
        self,
        # contract terms
        ccy: str,
        value_date: str | date,
        issue_date: str | date,
        maturity: str | date,
        receiving_leg: dict,  # typically fixed
        paying_leg: dict,  # typically floating
        # market data (flat/bootstrapped curves as dicts of tenors/rates)
        discount_curve: dict | None = None,
        forecast_curve: dict | None = None,
        pos_name: str | None = None,
    ):
        self.posName = pos_name
        self.ccy = ccy

        # Parse dates (accepts ISO strings or date objects)
        self.valueDate = value_date if isinstance(value_date, date) else date.fromisoformat(value_date)
        self.issue_date = issue_date if isinstance(issue_date, date) else date.fromisoformat(issue_date)
        self.maturity = maturity if isinstance(maturity, date) else date.fromisoformat(maturity)

        # QuantLib Date views
        self.ql_value_date = Date(self.valueDate.day, self.valueDate.month, self.valueDate.year)
        self.ql_issue_date = Date(self.issue_date.day, self.issue_date.month, self.issue_date.year)
        self.ql_maturity = Date(self.maturity.day, self.maturity.month, self.maturity.year)

        # Day count to build curves (stays local to this wrapper; legs use their own DC)
        self.ql_curve_day_count = Actual360()

        # Keep original leg specs & curve dicts
        self.paying_leg_spec = paying_leg
        self.receiving_leg_spec = receiving_leg
        self.discount_curve = discount_curve
        self.forecast_curve = forecast_curve

        # Quick access to types (used for diagnostics)
        self.paying_leg_type = paying_leg["leg_type"]
        self.receiving_leg_type = receiving_leg["leg_type"]

        # Built artifacts (populated during MTM)
        self.paying_leg_ql = None
        self.receiving_leg_ql = None
        self.swap: InterestRateSwap | None = None
        self.cash_flows = None  # DataFrame from swap.cashflow_table()

    # ---------- helpers ----------
    def _build_curve_handles(
        self,
    ) -> tuple[YieldTermStructureHandle, YieldTermStructureHandle]:
        """
        Build QL ZeroCurve handles for discounting & forecasting using MarketDataMapper.
        """
        if self.discount_curve is None or self.forecast_curve is None:
            raise ValueError("Both discount_curve and forecast_curve must be provided.")

        md = MarketDataMapper()

        # Discount curve
        md.addCurveData(
            curveName="DISCOUNT_CURVE",
            tenors=self.discount_curve["tenors"],
            seriesValues=np.array(self.discount_curve["rates"]),
        )
        disc = md.getCurveData("DISCOUNT_CURVE")
        disc.init_curve(self.ql_value_date, self.ql_curve_day_count)
        ql_discount_curve = disc.ql_ZeroCurve()
        ql_discount_handle = YieldTermStructureHandle(ql_discount_curve)

        # Forecast curve
        md.addCurveData(
            curveName="FORECAST_CURVE",
            tenors=self.forecast_curve["tenors"],
            seriesValues=np.array(self.forecast_curve["rates"]),
        )
        fwd = md.getCurveData("FORECAST_CURVE")
        fwd.init_curve(self.ql_value_date, self.ql_curve_day_count)
        ql_forecast_curve = fwd.ql_ZeroCurve()
        ql_forecast_handle = YieldTermStructureHandle(ql_forecast_curve)

        return ql_discount_handle, ql_forecast_handle

    def _apply_last_fixing_if_any(self, index, floating_leg) -> None:
        """
        If a current fixing is provided in the paying leg spec, add it at the last
        fixing date strictly before the valuation date.
        """
        if "curr_fixing" not in self.paying_leg_spec:
            return
        # Derive fixing dates from the floating leg coupons
        fl_coupons = floating_leg.cashflows
        if not fl_coupons:
            return
        fixing_dates = tuple(as_floating_rate_coupon(cf).fixingDate() for cf in fl_coupons)
        past_fixings = [d for d in fixing_dates if d < self.ql_value_date]
        if not past_fixings:
            return
        last_fixing_date = past_fixings[-1]
        index.addFixing(last_fixing_date, float(self.paying_leg_spec["curr_fixing"]), True)

    def _get_used_risk_factors(self) -> dict:
        """
        Flatten the cashflow table; include nominals if amortized floating.
        """
        if self.cash_flows is None:
            return {}
        return_dict = self.cash_flows.reset_index().to_dict(orient="list")
        if self.paying_leg_type == "amortized_floating" and hasattr(self.paying_leg_ql, "nominals"):
            return_dict["nominals"] = self.paying_leg_ql.nominals
        return return_dict

    def _get_warning(self) -> str:
        """
        Simple diagnostic when many zero-nominal periods exist on the floating leg.
        """
        try:
            zeros = self.paying_leg_ql.nominals.count(0)
            if zeros > 1:
                return f"Number of 0 nominals in cash flows: {zeros}"
        except Exception:
            pass
        return ""

    def _build_leg_object(self, leg_data: dict) -> FixedLeg | FloatingLeg:
        """
        Map to pricingengine swap-leg classes and instantiate.

        Notes:
        - Do NOT pass valuation_date; legs use Settings.evaluationDate.
        - Floating/amortized_floating legs must be created with an index.
          We pass a placeholder index bound to an empty handle; the real
          forecast index is injected later via with_index().
        """
        leg_class = QL_swap_leg_mapper[leg_data["leg_type"]].value

        kwargs = {
            "issue_date": self.ql_issue_date,
            "maturity": self.ql_maturity,
            "nominal": leg_data["nominal"],
            "currency": self.ccy,
            "tenor": Period(leg_data["tenor"]),
            "calendar": TARGET(),  # hardcoded is fine here
            "day_counter": QL_day_count_mapper[leg_data["day_count"]].value,
        }

        # For floating variants, supply a placeholder index; we’ll rebind in MTM.
        if leg_data["leg_type"] in ("floating", "amortized_floating"):
            placeholder_handle = YieldTermStructureHandle()  # empty link placeholder
            kwargs["index"] = generic_ibor(leg_data["tenor"], self.ccy, placeholder_handle)

        # Optional fields with light transformations
        for key in (
            "rate",  # fixed
            "gearing",
            "spread",  # ibor
            "per_coupon_nominals",  # amortization
        ):
            if key not in leg_data:
                continue
            value = leg_data[key]
            if key == "amortization_period":
                value = Period(value)
            elif key in ("amortization_first_date", "amortization_last_date"):
                vdate = value if isinstance(value, date) else date.fromisoformat(value)
                value = Date(vdate.day, vdate.month, vdate.year)
            kwargs[key] = value

        return leg_class(**kwargs)

    # ---------- public API ----------
    def valuePosition(self) -> float:
        """
        Single entry point:
          - sets the QL global evaluation date via ql_eval_date
          - (re)builds legs, curves, index and the swap
          - captures cashflow table for used risk factors
          - returns PV (swap NPV)
        """
        with ql_eval_date(self.ql_value_date):
            # 1) Build legs (they read Settings.evaluationDate internally)
            self.paying_leg_ql = self._build_leg_object(self.paying_leg_spec)
            self.receiving_leg_ql = self._build_leg_object(self.receiving_leg_spec)

            # 2) Curves
            ql_discount_handle, ql_forecast_handle = self._build_curve_handles()

            # 3) Real index on the forecast curve (use paying leg tenor)
            forecast_index = generic_ibor(self.paying_leg_spec["tenor"], self.ccy, ql_forecast_handle)

            # 4) Bind index to the floating leg (mapping guarantees paying is floating in our uses)
            self.paying_leg_ql = self.paying_leg_ql.with_index(forecast_index)

            # 5) Apply current fixing, if provided
            self._apply_last_fixing_if_any(forecast_index, self.paying_leg_ql)

            # 6) Build swap
            self.swap = InterestRateSwap(
                receiving_leg=self.receiving_leg_ql,
                paying_leg=self.paying_leg_ql,
                discount_curve=ql_discount_handle,
            )

            # 7) Cache a cashflow table for used risk factors
            self.cash_flows = self.swap.cashflow_table()

            # 8) Return PV
            return self.swap.npv()

    def MTM(self) -> tuple[float, dict, str]:
        """
        Thin wrapper around valuePosition():
          - calls valuePosition() to build & price
          - returns (PV, used_risk_factors, warning)
        """
        pv = self.valuePosition()
        used_risk_factors = self._get_used_risk_factors()
        warning = self._get_warning()
        return pv, used_risk_factors, warning
