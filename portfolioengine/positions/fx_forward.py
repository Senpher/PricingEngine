from __future__ import annotations

from datetime import date

import numpy as np
from QuantLib import (
    Actual360,
    Date,
    YieldTermStructureHandle,
    QuoteHandle,
    SimpleQuote,
    TARGET,
    ModifiedFollowing,
)
from pricingengine.instruments.fx_forward import (
    FxForward,
)

from rvs_engine_interface.client_positions.QL_Mapping import fx_base_price_invert
from rvs_engine_interface.client_positions.QL_Mapping import ql_eval_date
from rvs_engine_interface.client_positions.client_positions import ClientPosition
from rvs_engine_interface.client_positions.market_data_mapper import MarketDataMapper


class FXForward(ClientPosition):
    def __init__(
        self,
        value_date: str,
        nominal: float,
        maturity: str | date,
        strike_price: float,
        fx_fwd_pts_curve: list[dict],
        discount_curve: dict,
        spot_rate: dict,
        posName: str = None,
    ):
        self.posName = posName
        self.valueDate = (
            date.fromisoformat(value_date)
            if not isinstance(value_date, date)
            else value_date
        )
        self.ql_value_date = Date(
            self.valueDate.day, self.valueDate.month, self.valueDate.year
        )

        self.nominal = nominal
        self.strikePrice = float(strike_price)
        self.baseCCY = spot_rate["base_ccy"]
        self.priceCCY = spot_rate["price_ccy"]
        self.baseCCYRate = float(spot_rate["base_ccy_rate"])
        self.priceCCYRate = float(spot_rate["price_ccy_rate"])

        self.maturity = (
            date.fromisoformat(maturity) if not isinstance(maturity, date) else maturity
        )
        self.day_count = Actual360()

        mdm = MarketDataMapper()
        mdm.addCurveData(
            curveName="DISCOUNT_CURVE",
            tenors=discount_curve["tenors"],
            seriesValues=np.array(discount_curve["rates"]),
        )
        # fx_fwd_pts_curve is a list of two dicts: one for BASE, one for PRICE (to USD)
        # keep both; we will triangulate PRICE/BASE forwards below
        mdm.addCurveData(
            curveName="BASE_FX_FWD_PTS_CURVE",
            tenors=fx_fwd_pts_curve[0]["tenors"],
            seriesValues=np.array(fx_fwd_pts_curve[0]["rates"]),
        )
        mdm.addCurveData(
            curveName="PRICE_FX_FWD_PTS_CURVE",
            tenors=fx_fwd_pts_curve[1]["tenors"],
            seriesValues=np.array(fx_fwd_pts_curve[1]["rates"]),
        )

        self.discountCurveData = mdm.getCurveData("DISCOUNT_CURVE")
        self.baseFXPointsCurveData = mdm.getCurveData("BASE_FX_FWD_PTS_CURVE")
        self.priceFXPointsCurveData = mdm.getCurveData("PRICE_FX_FWD_PTS_CURVE")

        # used risk factors (cached after first valuation)
        self.discount_factor = None
        self.forward_rate = None
        self.spot_rate = None

    # ---------------- core valuation ----------------
    def valuePosition(self) -> float:
        with ql_eval_date(self.ql_value_date):
            self.discountCurveData.init_curve(self.ql_value_date, self.day_count)
            self.baseFXPointsCurveData.init_curve(self.ql_value_date, self.day_count)
            self.priceFXPointsCurveData.init_curve(self.ql_value_date, self.day_count)

            discount_handle = YieldTermStructureHandle(
                self.discountCurveData.ql_ZeroCurve()
            )

            # Compute spot S (PRICE/BASE), respecting market inversion flags
            if fx_base_price_invert(self.baseCCY):
                base_spot = 1.0 / self.baseCCYRate
            else:
                base_spot = self.baseCCYRate

            if fx_base_price_invert(self.priceCCY):
                price_spot = 1.0 / self.priceCCYRate
            else:
                price_spot = self.priceCCYRate

            s = price_spot / base_spot
            spot_handle = QuoteHandle(SimpleQuote(s))

            # Build PRICE/BASE forward points list[dict] for the pricingengine FxForward
            # Inputs are to-USD forward points in "rates" (pips). Convert to outrights vs USD, invert if needed,
            # triangulate PRICE/BASE outrights, then points = F - S.
            base_pts = np.array(self.baseFXPointsCurveData.seriesValues, dtype=float)
            price_pts = np.array(self.priceFXPointsCurveData.seriesValues, dtype=float)

            # points are given in pips -> convert to price terms: add to spot-to-USD
            price_fwd_to_usd = self.priceCCYRate + price_pts * (1.0 / 1000.0)
            base_fwd_to_usd = self.baseCCYRate + base_pts * (1.0 / 1000.0)

            # apply inversion convention (same as for spot)
            if fx_base_price_invert(self.priceCCY):
                price_fwd_to_usd = 1.0 / price_fwd_to_usd
            if fx_base_price_invert(self.baseCCY):
                base_fwd_to_usd = 1.0 / base_fwd_to_usd

            # triangulate PRICE/BASE outrights and compute points
            implied_f = price_fwd_to_usd / base_fwd_to_usd
            points_price_base = implied_f - s  # PRICE terms, same direction as spot

            # assemble list[dict] for FxForward (tenor strings + points)
            tenors = (
                self.priceFXPointsCurveData.ql_tenors
            )  # original tenor strings from MarketDataMapper
            fx_pts_curve = [
                {"tenor": str(ten), "points": float(pts)}
                for ten, pts in zip(tenors, points_price_base)
            ]

            # Instantiate pricingengine FxForward (it bootstraps the foreign curve via FxSwapRateHelper)
            ql_maturity = Date(
                self.maturity.day, self.maturity.month, self.maturity.year
            )
            engine = FxForward(
                nominal=self.nominal if self.nominal >= 0 else -self.nominal,
                forward_price=self.strikePrice,
                maturity=ql_maturity,
                base_currency=self.baseCCY,
                price_currency=self.priceCCY,
                long_base=(self.nominal >= 0),
                spot=spot_handle,
                discount_domestic=discount_handle,
                fx_fwd_pts_curve=fx_pts_curve,
                day_counter=self.day_count,  # Act/360
                fixing_days=2,
                calendar=TARGET(),  # or a JointCalendar(US, NOK) if desired
                convention=ModifiedFollowing,
                end_of_month=False,
                base_currency_is_collateral=False,  # PRICE-ccy collateral by default
            )

            # Price & collect diagnostics
            res = engine.npv(breakdown=True)
            pv = float(res["npv"])

            # cache used factors (only once, identical to your original behavior)
            if self.discount_factor is None:
                self.discount_factor = float(res["discount_factor"])
                self.forward_rate = float(res["market_forward"])
            self.spot_rate = float(s)

        return pv

    def getUsedRiskFactorDict(self) -> dict:
        return {
            "spot_rate": self.spot_rate,
            "forward_rate": self.forward_rate,
            "discount_factor": self.discount_factor,
        }

    def MTM(self) -> tuple[float, dict, None]:
        mtm = self.valuePosition()
        used_risk_factors = self.getUsedRiskFactorDict()
        warning_message = None
        return mtm, used_risk_factors, warning_message
