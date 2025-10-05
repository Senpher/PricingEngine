from __future__ import annotations

import numpy as np
from QuantLib import (
    Actual360,
    Actual365Fixed,
    BlackVolTermStructureHandle,
    Continuous,
    Date,
    QuoteHandle,
    SimpleQuote,
    YieldTermStructureHandle,
)
from QuantLib import (
    Option as QLOption,
)
from datetime import date
from typing import Literal

# pricingengine instruments
from pricingengine.instruments.equity_option import (
    AmericanVanillaOption,
    BermudanVanillaOption,
    EuropeanDigitalOption,
    EuropeanVanillaOption,
    OptionEngineParameters,
)
from .client_positions import ClientPosition
from ..data_structures.ql_mapping import ql_eval_date
from ..data_structures.market_data_mapper import MarketDataMapper


class EquityOption(ClientPosition):
    """
    Inputs are dicts/lists
    in MarketDataMapper, and only inside `valuePosition()` we build the QL objects.

    Required market data dicts:
      - spot: {"value": float}
      - discount_curve: {"tenors": [...], "rates": [...]}    # risk-free curve
      - dividend_curve: {"tenors": [...], "rates": [...]}    # continuous dividend yield
      - vol_curve: {"tenors": [...], "vols": [...]}          # Black vols (atm or given)

    Style / engine:
      - style: "european" | "american" | "bermudan" | "digital"
      - engine: one of {"analytic","fd","baw","bjerksund","tree"}
        (tree needs {"steps": int, "method": str}, fd may use {"nt": int, "nx": int})

    Bermudan: provide `exercise_dates` as list of ISO strings or `date`s.
    Digital: provide `cash_payoff` (float).
    """

    def __init__(
        self,
        *,
        value_date: str | date,
        is_call: bool = True,
        style: Literal["european", "american", "bermudan", "digital"],
        strike: float,
        # not used for bermudan if exercise_dates provided
        maturity: str | date | None = None,
        exercise_dates: list[str | date] | None = None,  # for bermudan
        cash_payoff: float | None = None,  # for digital
        nominal: int = 1,
        contract_size: int = 100,
        ccy: str,
        # e.g. {"nt":121,"nx":241} for fd; {"steps":201,"method":"lr"} for tree
        engine_params: dict | None = None,
        # market data (raw dicts, like FX/IRS wrappers)
        spot: float,
        discount_curve: dict,
        dividend_curve: dict,
        vol_surface: dict,
        pos_name: str | None = None,
    ):
        self.posName = pos_name
        self.valueDate = date.fromisoformat(value_date) if not isinstance(value_date, date) else value_date
        self.ql_value_date = Date(self.valueDate.day, self.valueDate.month, self.valueDate.year)

        self.spot = spot
        self.optionTypeBool = is_call
        self.optionTypeQL = QLOption.Call if self.optionTypeBool else QLOption.Put
        self.style = style.lower()
        self.strike = float(strike)
        self.quantity = int(nominal)
        self.contractSize = int(contract_size)
        self.ccy = ccy

        # maturity or exercise dates
        self.maturity = (
            None if maturity is None else (date.fromisoformat(maturity) if not isinstance(maturity, date) else maturity)
        )
        if exercise_dates:
            self.exerciseDates = [(date.fromisoformat(d) if not isinstance(d, date) else d) for d in exercise_dates]
        else:
            self.exerciseDates = None

        self.day_count = Actual360()

        # style sanity
        if self.style not in {"european", "american", "bermudan", "digital"}:
            raise ValueError("style must be one of {'european','american','bermudan','digital'}")
        if self.style != "bermudan" and self.maturity is None:
            raise ValueError("maturity is required unless style='bermudan'")
        if self.style == "bermudan" and not self.exerciseDates:
            raise ValueError("exercise_dates are required for style='bermudan'")
        if self.style == "digital" and (cash_payoff is None):
            raise ValueError("cash_payoff must be provided for digital options")
        self.cashPayoff = float(cash_payoff) if cash_payoff is not None else None

        # engine selection (we pass a *factory* at valuation time)
        self.engineParams = dict(engine_params or {})

        mdm = MarketDataMapper()
        mdm.add_curve_data(
            curve_name="DISCOUNT_CURVE",
            tenors=discount_curve["tenors"],
            series_values=np.array(discount_curve["rates"]),
        )
        mdm.add_curve_data(
            curve_name="DIVIDEND_CURVE",
            tenors=dividend_curve["tenors"],
            series_values=np.array(dividend_curve["rates"]),
        )
        mdm.add_surface_data(
            surface_name="EQ_VOL_SURFACE",
            tenors=vol_surface["tenors"],
            strikes=np.array(vol_surface["strikes"], dtype=float),  # moneyness = spot/strike
            series_values=np.array(vol_surface["vols"], dtype=float),
        )

        # stash mapped curve data
        self.discountCurveData = mdm.get_curve_data("DISCOUNT_CURVE")
        self.dividendCurveData = mdm.get_curve_data("DIVIDEND_CURVE")
        self.volSurfaceData = mdm.get_surface_data("EQ_VOL_SURFACE")

        # used risk factors cache (filled on first price)
        self.used_spot = None
        self.used_df = None
        self.used_rf = None
        self.used_dq = None
        self.used_rq = None
        self.used_vol = None
        self.used_engine = None
        self.ql_maturity = None
        self.maturity_yf = None

    def _resolve_engine_params(self, ep: dict | None):
        """
        Decide engine based on provided dict, or pick defaults by style.
        Returns (OptionEngineParameters, engine_key_str).
        """
        if not ep:
            # style-specific defaults
            if self.style in {"european", "digital"}:
                return OptionEngineParameters.analytic(), "analytic"
            if self.style == "american":
                return OptionEngineParameters.baw(), "baw"
            if self.style == "bermudan":
                return OptionEngineParameters.tree(steps=201, method="lr"), "tree method:{} steps:{}".format("lr", 201)
            raise ValueError(f"Unsupported style '{self.style}'")

        key = str(ep.get("engine", "")).lower().strip()
        if key == "analytic":
            return OptionEngineParameters.analytic(), "analytic"
        if key == "fd":
            nt = int(ep.get("nt", 121))
            nx = int(ep.get("nx", 241))
            return OptionEngineParameters.fd(nt=nt, nx=nx), "fd nt:{} nx:{}".format(nt, nx)
        if key == "baw":
            return OptionEngineParameters.baw(), "baw"
        if key == "bjerksund":
            return OptionEngineParameters.bjerksund(), "bjerksund"
        if key == "tree":
            if "steps" not in ep or "method" not in ep:
                raise ValueError("tree engine requires 'steps' and 'method'")
            steps = int(ep["steps"])
            method = str(ep["method"])
            return OptionEngineParameters.tree(method=method, steps=steps), "tree method:{} steps:{}".format(
                method, steps
            )

        raise ValueError(f"Unknown engine '{key}' in engine_params")

    # ---------------- core valuation ----------------
    def valuePosition(self) -> float:
        """
        Build QL objects and price with pricingengine instruments.
        """
        with ql_eval_date(self.ql_value_date):
            # --- spot ---
            spot = QuoteHandle(SimpleQuote(self.spot))

            self.discountCurveData.init_curve(self.ql_value_date, Actual360())
            self.dividendCurveData.init_curve(self.ql_value_date, Actual360())
            self.volSurfaceData.init_surface(self.ql_value_date, Actual365Fixed())

            disc_curve = YieldTermStructureHandle(self.discountCurveData.ql_zero_curve())
            div_curve = YieldTermStructureHandle(self.dividendCurveData.ql_zero_curve())

            ql_surf = self.volSurfaceData.ql_surface(spot_rate=self.spot)
            vol_handle = BlackVolTermStructureHandle(ql_surf)

            # --- select engine params (OptionEngineParameters.*()) ---
            eng_p, self.used_engine = self._resolve_engine_params(self.engineParams)

            # --- choose instrument class by style ---
            self.ql_maturity = (
                Date(self.maturity.day, self.maturity.month, self.maturity.year) if self.maturity is not None else None
            )

            if self.style == "european":
                opt = EuropeanVanillaOption(
                    quantity=self.quantity,
                    contract_size=self.contractSize,
                    option_type=self.optionTypeQL,
                    strike=self.strike,
                    maturity=self.ql_maturity,
                    engine_params=eng_p,
                    # market inputs
                    spot=spot,
                    dividend_curve=div_curve,
                    risk_free_curve=disc_curve,
                    vol=vol_handle,
                )
            elif self.style == "american":
                opt = AmericanVanillaOption(
                    quantity=self.quantity,
                    contract_size=self.contractSize,
                    option_type=self.optionTypeQL,
                    strike=self.strike,
                    maturity=self.ql_maturity,
                    engine_params=eng_p,
                    spot=spot,
                    dividend_curve=div_curve,
                    risk_free_curve=disc_curve,
                    vol=vol_handle,
                )
            elif self.style == "bermudan":
                if not self.exerciseDates:
                    raise ValueError("exercise_dates required for bermudan")
                ql_ex_dates = [Date(d.day, d.month, d.year) for d in self.exerciseDates]
                opt = BermudanVanillaOption(
                    quantity=self.quantity,
                    contract_size=self.contractSize,
                    option_type=self.optionTypeQL,
                    strike=self.strike,
                    exercise_dates=tuple(ql_ex_dates),
                    engine_params=eng_p,
                    spot=spot,
                    dividend_curve=div_curve,
                    risk_free_curve=disc_curve,
                    vol=vol_handle,
                )
            elif self.style == "digital":
                opt = EuropeanDigitalOption(
                    quantity=self.quantity,
                    contract_size=self.contractSize,
                    option_type=self.optionTypeQL,
                    strike=self.strike,
                    maturity=self.ql_maturity,
                    cash_payoff=float(self.cashPayoff),
                    engine_params=eng_p,
                    spot=spot,
                    dividend_curve=div_curve,
                    risk_free_curve=disc_curve,
                    vol=vol_handle,
                )
            else:
                raise ValueError("'style' error or not implemented")

            # price (per your internal instrument this returns per-unit; we multiply)
            pv_per_unit = opt.npv_per_unit()
            pv = pv_per_unit * self.quantity * self.contractSize

            # collect used risk factors (first run or update every time—your call)
            self.used_spot = float(self.spot)
            # for “DF/q/vol at maturity”, probe at the *last* exercise (european/digital -> maturity)
            probe_date = (
                opt.maturity
                if hasattr(opt, "maturity") and opt.maturity
                else (opt.exercise_dates[-1] if hasattr(opt, "exercise_dates") else self.ql_value_date)
            )
            try:
                self.used_df = float(disc_curve.discount(probe_date))
                self.used_rf = float(disc_curve.zeroRate(probe_date, self.day_count, Continuous).rate())
            except Exception:
                self.used_df = None
                self.used_rf = None
            try:
                self.used_dq = float(div_curve.discount(probe_date))
                self.used_rq = float(div_curve.zeroRate(probe_date, self.day_count, Continuous).rate())
            except Exception:
                self.used_dq = None
                self.used_rq = None
            try:
                # ATM vol for diagnostics (Q.L. wants time or date; we use date overload)
                self.used_vol = float(vol_handle.blackVol(probe_date, self.strike))
            except Exception:
                self.used_vol = None

            try:
                self.maturity_yf = disc_curve.dayCounter().yearFraction(disc_curve.referenceDate(), self.ql_maturity)
            except Exception:
                self.maturity_yf = None

        return float(pv)

    def MTM(self) -> tuple[float, dict, None]:
        mtm = self.valuePosition()
        used = self.getUsedRiskFactorDict()
        return mtm, used, None

    def getUsedRiskFactorDict(self) -> dict:
        return {
            "spot": self.used_spot,
            "discount_factor": self.used_df,
            "discount_rate": self.used_rf,
            "dividend_df": self.used_dq,
            "dividend_rf": self.used_rq,
            "atm_vol": self.used_vol,
            "strike": self.strike,
            "quantity": self.quantity,
            "contract_size": self.contractSize,
            "style": self.style,
            "engine params": self.engineParams,
            "engine": self.used_engine,
            "maturity": self.ql_maturity,
            "maturity year fraction": self.maturity_yf,
        }
