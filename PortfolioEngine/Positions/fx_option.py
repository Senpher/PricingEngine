from __future__ import annotations

from datetime import date

from QuantLib import Date

from PortfolioEngine.DataStructures import ql_eval_date
from PortfolioEngine.Positions import ClientPosition, OptionStyleKey
from PortfolioEngine.Positions import EquityOption as PortfolioEquityOption


class FXOption(ClientPosition):
    """
    Thin adapter around the portfolio engine EquityOption wrapper, but using *price/base* terminology.

    Spot mapping:
      fx_spot = price_ccy_rate / base_ccy_rate
      passed to EquityOption as: spot={"value": fx_spot}

    Curve mapping:
      price_discount_curve -> EquityOption.discount_curve  (r in GK)
      base_discount_curve  -> EquityOption.dividend_curve  (q in GK)

    Vol surface:
      pass through to EquityOption.vol_surface (it uses MarketDataMapper.addSurfaceData).

    Engine:
      You can pass `engine` explicitly (e.g., "analytic", "fd", "tree", ...),
      and complementary parameters in `engine_params`. If you omit `engine`,
      the EquityOption default is used; if you only provide engine via
      `engine_params["engine"]`, it's forwarded as well.
    """

    def __init__(
        self,
        *,
        pos_name: str | None,
        value_date: str | date,
        is_call: bool,
        style: OptionStyleKey,
        strike: float,
        # European/Digital -> maturity; Bermudan -> exercise_dates
        maturity: str | date | None = None,
        exercise_dates: list[str | date] | None = None,
        # Digital
        cash_payoff: float | None = None,
        nominal: int = 1,
        contract_size: int = 100,
        # FX spot as a dict
        spot: dict,  # {"base_ccy","price_ccy","base_ccy_rate","price_ccy_rate"}
        # market data dicts (price/base, not domestic/foreign)
        price_discount_curve: dict,  # -> EquityOption.discount_curve  (r)
        base_discount_curve: dict,  # -> EquityOption.dividend_curve (q)
        vol_surface: dict,  # -> EquityOption.vol_surface
        # engine selection
        engine_params: dict | None = None,
    ):
        self.posName = pos_name

        # normalize valuation date
        self.valueDate = value_date if isinstance(value_date, date) else date.fromisoformat(value_date)
        self.ql_value_date = Date(self.valueDate.day, self.valueDate.month, self.valueDate.year)

        # FX spot components (price/base)
        self.baseCCY = spot["base_ccy"]
        self.priceCCY = spot["price_ccy"]
        self.baseRate = float(spot["base_ccy_rate"])
        self.priceRate = float(spot["price_ccy_rate"])
        self.fx_spot = self.priceRate / self.baseRate  # price per 1 base

        # stash MD dicts to pass through
        self._price_discount_curve = price_discount_curve
        self._base_discount_curve = base_discount_curve
        self._vol_surface = vol_surface

        # cache diagnostics
        self._used: dict = {}

        self._eq_kwargs = {
            "value_date": self.valueDate,
            "is_call": is_call,
            "style": style,
            "strike": float(strike),
            "maturity": maturity,
            "exercise_dates": exercise_dates,
            "cash_payoff": cash_payoff,
            "nominal": int(nominal),
            "contract_size": int(contract_size),
            "engine_params": engine_params,
            "pos_name": self.posName,
            "ccy": self.priceCCY,  # position currency = PRICE currency
        }

    # ------------- core valuation -------------
    def value_position(self) -> float:
        """Build a portfolio EquityOption with mapped inputs and delegate pricing."""
        eq = PortfolioEquityOption(
            **self._eq_kwargs,
            spot=self.fx_spot,
            discount_curve=self._price_discount_curve,  # r (price currency)
            dividend_curve=self._base_discount_curve,  # q (base currency)
            vol_surface=self._vol_surface,
        )

        with ql_eval_date(self.ql_value_date):
            mtm = eq.value_position()

        # Pass-through diagnostics + FX details
        self._used = eq.get_used_risk_factor_dict() | {
            "fx_spot": self.fx_spot,
            "fx_base_ccy": self.baseCCY,
            "fx_price_ccy": self.priceCCY,
            "fx_base_rate": self.baseRate,
            "fx_price_rate": self.priceRate,
        }
        return float(mtm)

    def MTM(self) -> tuple[float, dict, None]:
        pv = self.value_position()
        return pv, self.get_used_risk_factor_dict(), None

    def get_used_risk_factor_dict(self) -> dict:
        if not self._used:
            _ = self.value_position()
        return dict(self._used)

    # ---- required interface bits ----
    def get_pos_currency(self) -> str:
        return self.priceCCY

    def get_pos_name(self) -> str:
        return self.posName

    def get_pos_type(self) -> str:
        return "fx_option"
