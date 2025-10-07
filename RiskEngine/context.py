from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from QuantLib import (
    Actual360,
    Actual365Fixed,
    BlackConstantVol,
    Date,
    NullCalendar,
    Period,
    RelinkableBlackVolTermStructureHandle,
    RelinkableQuoteHandle,
    RelinkableYieldTermStructureHandle,
    Settings,
    SimpleQuote,
    ZeroCurve,
)


@dataclass
class MarketContext:
    """Relinkable handles + simple quotes the portfolio will use."""

    as_of: Date
    discount: dict[str, RelinkableYieldTermStructureHandle]
    dividend: dict[str, RelinkableYieldTermStructureHandle]
    vols: dict[str, RelinkableBlackVolTermStructureHandle]
    equity_spot: dict[str, RelinkableQuoteHandle]
    fx_spot: dict[tuple[str, str], RelinkableQuoteHandle]
    fx_fwd_points: dict[tuple[str, str], dict[str, RelinkableQuoteHandle]]

    @classmethod
    def build_dummy(cls) -> MarketContext:
        as_of = Date(24, 7, 2025)
        Settings.instance().evaluationDate = as_of
        dc360 = Actual360()
        dc365 = Actual365Fixed()

        def zero_curve(rates, tenors):
            dates = [as_of] + [as_of + Period(t) for t in tenors]
            levels = [rates[0], *list(rates)]
            curve = ZeroCurve(dates, levels, dc360)
            curve.enableExtrapolation()
            return curve

        sek_disc_base = zero_curve(
            [0.0185, 0.0182, 0.0180, 0.0181, 0.0184, 0.0190],
            ["1M", "3M", "6M", "9M", "1Y", "2Y"],
        )
        usd_disc_base = zero_curve(
            [0.045, 0.044, 0.043, 0.0425, 0.0420, 0.041],
            ["1M", "3M", "6M", "9M", "1Y", "2Y"],
        )
        rl_sek = RelinkableYieldTermStructureHandle(sek_disc_base)
        rl_usd = RelinkableYieldTermStructureHandle(usd_disc_base)
        discount = {"SEK": rl_sek, "USD": rl_usd}

        def flat_zero(level):
            dates = [as_of, as_of + Period("10Y")]
            rates = [level, level]
            curve = ZeroCurve(dates, rates, dc360)
            curve.enableExtrapolation()
            return curve

        dividend = {
            "OMX": RelinkableYieldTermStructureHandle(flat_zero(0.008)),
            "SPX": RelinkableYieldTermStructureHandle(flat_zero(0.015)),
        }

        def flat_vol(level):
            return BlackConstantVol(as_of, NullCalendar(), level, dc365)

        vols = {
            "OMX_ATM": RelinkableBlackVolTermStructureHandle(flat_vol(0.18)),
            "SPX_ATM": RelinkableBlackVolTermStructureHandle(flat_vol(0.22)),
        }
        # Equity spot
        equity_spot_quotes = {
            "OMX": SimpleQuote(2600.22),
            "SPX": SimpleQuote(5400.0),
        }
        equity_spot = {k: RelinkableQuoteHandle(v) for k, v in equity_spot_quotes.items()}
        # FX spot
        fx_spot_quotes = {("SEK", "USD"): SimpleQuote(9.60)}
        fx_spot = {k: RelinkableQuoteHandle(v) for k, v in fx_spot_quotes.items()}
        # FX forward points
        fx_fwd_point_quotes = {
            ("SEK", "USD"): {
                "1M": SimpleQuote(+0.010),
                "3M": SimpleQuote(+0.025),
                "6M": SimpleQuote(+0.045),
                "1Y": SimpleQuote(+0.085),
            }
        }
        fx_fwd_points = {
            k: {tenor: RelinkableQuoteHandle(q) for tenor, q in v.items()} for k, v in fx_fwd_point_quotes.items()
        }
        return cls(
            as_of=as_of,
            discount=discount,
            dividend=dividend,
            vols=vols,
            equity_spot=equity_spot,
            fx_spot=fx_spot,
            fx_fwd_points=fx_fwd_points,
        )

    @contextmanager
    def at_eval(self):
        saved = Settings.instance().evaluationDate
        try:
            Settings.instance().evaluationDate = self.as_of
            yield
        finally:
            Settings.instance().evaluationDate = saved

    def copy(self) -> MarketContext:
        """Create a shallow copy of the MarketContext with new handles and quotes."""
        # Recreate all handles and quotes using the same values
        as_of = Date(self.as_of.dayOfMonth(), self.as_of.month(), self.as_of.year())
        discount = {k: RelinkableYieldTermStructureHandle(v.currentLink()) for k, v in self.discount.items()}
        dividend = {k: RelinkableYieldTermStructureHandle(v.currentLink()) for k, v in self.dividend.items()}
        vols = {k: RelinkableBlackVolTermStructureHandle(v.currentLink()) for k, v in self.vols.items()}
        equity_spot = {k: RelinkableQuoteHandle(v.currentLink()) for k, v in self.equity_spot.items()}
        fx_spot = {k: RelinkableQuoteHandle(v.currentLink()) for k, v in self.fx_spot.items()}
        fx_fwd_points = {
            k: {tenor: RelinkableQuoteHandle(q.currentLink()) for tenor, q in v.items()}
            for k, v in self.fx_fwd_points.items()
        }
        return MarketContext(
            as_of=as_of,
            discount=discount,
            dividend=dividend,
            vols=vols,
            equity_spot=equity_spot,
            fx_spot=fx_spot,
            fx_fwd_points=fx_fwd_points,
        )
