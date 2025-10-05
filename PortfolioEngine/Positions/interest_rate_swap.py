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

from PortfolioEngine.DataStructures import (
    GenericIbor,
    MarketDataMapper,
    QlDayCountMapper,
    QlSwapLegMapper,
    ql_eval_date,
)
from PortfolioEngine.Positions import ClientPosition
from PricingEngine.Instruments import InterestRateSwap
from PricingEngine.Instruments.Common import FixedLeg, FloatingLeg


class IRS(ClientPosition):
    """
    PortfolioEngine wrapper around PricingEngine.InterestRateSwap.

    - Uses QuantLib global Settings.evaluationDate via ql_eval_date().
    - Builds legs via PricingEngine leg classes (through QlSwapLegMapper).
    - Builds discount and forecast handles from the dicts in `factors`.
    - For floating legs, builds a local GenericIbor(index, handle) and, if provided,
      adds a 'curr_fixing' on the last fixing date strictly before the valuation date.
    - Exposes `self.swap`, `self.cash_flows`, and returns (pv, used_factors, warning) in MTM().
    """

    def __init__(
        self,
        ccy: str,
        value_date: str | date,
        issue_date: str | date,
        maturity: str | date,
        receiving_leg: dict,
        paying_leg: dict,
        discount_curve: dict | None = None,
        forecast_curve: dict | None = None,
        pos_name: str | None = None,
    ):
        self.posName = pos_name
        self.ccy = ccy

        # Accept ISO strings or datetime.date
        self.valueDate = value_date if isinstance(value_date, date) else date.fromisoformat(str(value_date))
        self.issue_date = issue_date if isinstance(issue_date, date) else date.fromisoformat(str(issue_date))
        self.maturity = maturity if isinstance(maturity, date) else date.fromisoformat(str(maturity))

        # QuantLib dates
        self.ql_value_date = Date(self.valueDate.day, self.valueDate.month, self.valueDate.year)
        self.ql_issue_date = Date(self.issue_date.day, self.issue_date.month, self.issue_date.year)
        self.ql_maturity = Date(self.maturity.day, self.maturity.month, self.maturity.year)

        # Day count for curve bootstrapping (legs use their own DCs)
        self.ql_curve_day_count = Actual360()

        # Keep raw specs
        self.paying_leg_spec = paying_leg
        self.receiving_leg_spec = receiving_leg
        self.discount_curve = discount_curve
        self.forecast_curve = forecast_curve

        # Quick access to types
        self.paying_leg_type = paying_leg["leg_type"]
        self.receiving_leg_type = receiving_leg["leg_type"]

        # Will be built during valuation
        self.ql_discount_handle: YieldTermStructureHandle | None = None
        self.ql_forecast_handle: YieldTermStructureHandle | None = None

        self.ql_paying_leg = None
        self.ql_receiving_leg = None
        self.swap: InterestRateSwap | None = None
        self.cash_flows = None  # DataFrame from PricingEngine swap.cashflow_table()

    # ---------- public API ----------

    def MTM(self):
        pv = self.value_position()
        return pv, self._get_used_risk_factors(), self._get_warning()

    def value_position(self) -> float:
        """
        Build curves & legs, then price. Also caches the cashflow table for used_factors().
        """
        with ql_eval_date(self.ql_value_date):
            self.ql_discount_handle, self.ql_forecast_handle = self._build_curve_handles()

            # Build legs (only floating legs consume the forecast handle)
            pay_handle = self.ql_forecast_handle if self.paying_leg_type in ("floating", "amortized_floating") else None
            rec_handle = (
                self.ql_forecast_handle if self.receiving_leg_type in ("floating", "amortized_floating") else None
            )

            self.ql_paying_leg = self._build_leg_object(self.paying_leg_spec, pay_handle)
            self.ql_receiving_leg = self._build_leg_object(self.receiving_leg_spec, rec_handle)

            # Construct instrument and price
            self.swap = InterestRateSwap(
                receiving_leg=self.ql_receiving_leg,
                paying_leg=self.ql_paying_leg,
                discount_curve=self.ql_discount_handle,
            )
            self.cash_flows = self.swap.cashflow_table()
            return self.swap.npv()

    # ---------- internals ----------

    def _build_curve_handles(self) -> tuple[YieldTermStructureHandle, YieldTermStructureHandle]:
        """
        Build discounting & forecasting handles from dicts (tenors + rates).
        """
        if self.discount_curve is None or self.forecast_curve is None:
            raise ValueError("Both discount_curve and forecast_curve must be provided.")

        md = MarketDataMapper()

        # Discount curve
        md.add_curve_data(
            curve_name="DISCOUNT_CURVE",
            tenors=self.discount_curve["tenors"],
            series_values=np.array(self.discount_curve["rates"], dtype=float),
        )
        disc = md.get_curve_data("DISCOUNT_CURVE")
        disc.init_curve(self.ql_value_date, self.ql_curve_day_count)
        ql_discount_handle = YieldTermStructureHandle(disc.ql_zero_curve())

        # Forecast curve (single dict per the tests; used by whichever leg is floating)
        md.add_curve_data(
            curve_name="FORECAST_CURVE",
            tenors=self.forecast_curve["tenors"],
            series_values=np.array(self.forecast_curve["rates"], dtype=float),
        )
        fwd = md.get_curve_data("FORECAST_CURVE")
        fwd.init_curve(self.ql_value_date, self.ql_curve_day_count)
        ql_forecast_handle = YieldTermStructureHandle(fwd.ql_zero_curve())

        return ql_discount_handle, ql_forecast_handle

    def _build_leg_object(
        self, leg_data: dict, forecast_handle: YieldTermStructureHandle | None
    ) -> FixedLeg | FloatingLeg:
        """
        Build a Fixed/Floating (or amortized) leg. For floating, bind a local GenericIbor
        to the provided forecast handle and, if 'curr_fixing' exists, add that fixing on
        the last fixing date strictly before valuation date.
        """
        leg_type = leg_data["leg_type"]
        leg_class = QlSwapLegMapper[leg_type].value  # -> FixedLeg or FloatingLeg (amortized variants map too)

        kwargs = {
            "issue_date": self.ql_issue_date,
            "maturity": self.ql_maturity,
            "nominal": leg_data["nominal"],
            "currency": self.ccy,
            "tenor": Period(leg_data["tenor"]),
            "calendar": TARGET(),
            "day_counter": QlDayCountMapper[leg_data["day_count"]].value,
        }

        # Optional straight-through fields
        for key in ("rate", "gearing", "spread", "per_coupon_nominals"):
            if key in leg_data:
                kwargs[key] = leg_data[key]

        if leg_type in ("floating", "amortized_floating"):
            if forecast_handle is None:
                raise ValueError("Floating leg requires a forecast handle.")
            # Local index bound to the correct handle
            index = GenericIbor(leg_data["tenor"], self.ccy, forecast_handle)
            kwargs["index"] = index
            leg = leg_class(**kwargs)

            # Add last past fixing when provided
            if "curr_fixing" in leg_data:
                fl_coupons = leg.cashflows
                if fl_coupons:
                    fixing_dates = tuple(as_floating_rate_coupon(cf).fixingDate() for cf in fl_coupons)
                    past = [d for d in fixing_dates if d < self.ql_value_date]
                    if past:
                        index.addFixing(past[-1], float(leg_data["curr_fixing"]), True)
        else:
            leg = leg_class(**kwargs)

        return leg

    # ---------- used factors / warnings ----------

    def _get_used_risk_factors(self) -> dict:
        """
        Convert cached cashflow table to lists (to match tests) and attach nominals if present.
        """
        if self.cash_flows is None:
            return {}
        rd = self.cash_flows.reset_index().to_dict(orient="list")

        # Attach nominals from the first leg that provides them (amortized cases)
        for leg in (self.ql_paying_leg, self.ql_receiving_leg):
            if hasattr(leg, "nominals"):
                rd["nominals"] = list(leg.nominals)
                break
        return rd

    def _get_warning(self) -> str:
        """
        Simple warning based on number of zero nominals in any amortized leg.
        """
        for leg in (self.ql_paying_leg, self.ql_receiving_leg):
            try:
                zeros = leg.nominals.count(0) if hasattr(leg, "nominals") else 0
                if zeros > 1:
                    return f"Number of 0 nominals in cash flows: {zeros}"
            except Exception:
                pass
        return ""
