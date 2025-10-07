from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from QuantLib import (
    Actual365Fixed,
    BlackConstantVol,
    Date,
    FlatForward,
    NullCalendar,
    QuoteHandle,
    RelinkableBlackVolTermStructureHandle,
    RelinkableYieldTermStructureHandle,
    SavedSettings,
    Settings,
    SimpleQuote,
)


@dataclass
class MarketContext:
    """Container for market data expressed as QuantLib handles.

    The context stores both the relinkable handles that instruments consume and
    the underlying :class:`~QuantLib.SimpleQuote` objects that scenarios mutate.
    """

    evaluation_date: Date
    base_currency: str = "SEK"
    discount: dict[str, RelinkableYieldTermStructureHandle] = field(default_factory=dict)
    discount_quotes: dict[str, SimpleQuote] = field(default_factory=dict)
    dividend: dict[str, RelinkableYieldTermStructureHandle] = field(default_factory=dict)
    dividend_quotes: dict[str, SimpleQuote] = field(default_factory=dict)
    vols: dict[str, RelinkableBlackVolTermStructureHandle] = field(default_factory=dict)
    vol_quotes: dict[str, SimpleQuote] = field(default_factory=dict)
    equity_spot: dict[str, QuoteHandle] = field(default_factory=dict)
    equity_spot_quotes: dict[str, SimpleQuote] = field(default_factory=dict)
    fx_spot: dict[tuple[str, str], QuoteHandle] = field(default_factory=dict)
    fx_spot_quotes: dict[tuple[str, str], SimpleQuote] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_date, Date):
            raise TypeError("evaluation_date must be a QuantLib.Date instance")

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def build_dummy(cls) -> MarketContext:
        """Create a simple context used in tests and tutorials.

        The dummy context includes:
        - SEK and USD discount curves (flat)
        - OMX dividend curve (flat)
        - Constant volatility surface for OMX
        - Spot quotes for OMX equity and USD/SEK FX
        """

        evaluation_date = Date(2, 1, 2024)
        ctx = cls(evaluation_date=evaluation_date, base_currency="SEK")

        ctx.add_discount_curve("SEK", rate=0.02)
        ctx.add_discount_curve("USD", rate=0.03)
        ctx.add_dividend_curve("OMX", rate=0.01)
        ctx.add_vol_surface("OMX_ATM", volatility=0.20)
        ctx.add_equity_spot("OMX", spot=2300.0)
        ctx.add_fx_spot(("SEK", "USD"), spot=0.095)
        ctx.add_fx_spot(("USD", "SEK"), spot=10.50)
        return ctx

    # ------------------------------------------------------------------
    # Adders
    # ------------------------------------------------------------------
    def add_discount_curve(self, currency: str, *, rate: float, day_counter: Actual365Fixed | None = None) -> None:
        quote = SimpleQuote(rate)
        dc = day_counter or Actual365Fixed()
        curve = FlatForward(self.evaluation_date, QuoteHandle(quote), dc)
        handle = RelinkableYieldTermStructureHandle()
        handle.linkTo(curve)
        self.discount[currency] = handle
        self.discount_quotes[currency] = quote

    def add_dividend_curve(self, equity: str, *, rate: float, day_counter: Actual365Fixed | None = None) -> None:
        quote = SimpleQuote(rate)
        dc = day_counter or Actual365Fixed()
        curve = FlatForward(self.evaluation_date, QuoteHandle(quote), dc)
        handle = RelinkableYieldTermStructureHandle()
        handle.linkTo(curve)
        self.dividend[equity] = handle
        self.dividend_quotes[equity] = quote

    def add_vol_surface(
        self,
        code: str,
        *,
        volatility: float,
        day_counter: Actual365Fixed | None = None,
        calendar: NullCalendar | None = None,
    ) -> None:
        vol_quote = SimpleQuote(volatility)
        dc = day_counter or Actual365Fixed()
        cal = calendar or NullCalendar()
        surface = BlackConstantVol(self.evaluation_date, cal, QuoteHandle(vol_quote), dc)
        handle = RelinkableBlackVolTermStructureHandle()
        handle.linkTo(surface)
        self.vols[code] = handle
        self.vol_quotes[code] = vol_quote

    def add_equity_spot(self, equity: str, *, spot: float) -> None:
        quote = SimpleQuote(spot)
        handle = QuoteHandle(quote)
        self.equity_spot[equity] = handle
        self.equity_spot_quotes[equity] = quote

    def add_fx_spot(self, pair: tuple[str, str], *, spot: float) -> None:
        quote = SimpleQuote(spot)
        handle = QuoteHandle(quote)
        self.fx_spot[pair] = handle
        self.fx_spot_quotes[pair] = quote

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    @contextmanager
    def at_eval(self) -> Iterator[MarketContext]:
        """Set QuantLib's global evaluation date while within the context."""

        with SavedSettings():
            Settings.instance().evaluationDate = self.evaluation_date
            yield self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def discount_handle(self, currency: str) -> RelinkableYieldTermStructureHandle:
        return self.discount[currency]

    def dividend_handle(self, equity: str) -> RelinkableYieldTermStructureHandle:
        return self.dividend[equity]

    def vol_handle(self, code: str) -> RelinkableBlackVolTermStructureHandle:
        return self.vols[code]

    def equity_spot_handle(self, equity: str) -> QuoteHandle:
        return self.equity_spot[equity]

    def fx_spot_handle(self, pair: tuple[str, str]) -> QuoteHandle:
        return self.fx_spot[pair]

    @property
    def discount_handles(self) -> Mapping[str, RelinkableYieldTermStructureHandle]:
        return MappingProxyType(self.discount)

    @property
    def dividend_handles(self) -> Mapping[str, RelinkableYieldTermStructureHandle]:
        return MappingProxyType(self.dividend)

    @property
    def vol_handles(self) -> Mapping[str, RelinkableBlackVolTermStructureHandle]:
        return MappingProxyType(self.vols)

    @property
    def equity_spot_handles(self) -> Mapping[str, QuoteHandle]:
        return MappingProxyType(self.equity_spot)

    @property
    def fx_spot_handles(self) -> Mapping[tuple[str, str], QuoteHandle]:
        return MappingProxyType(self.fx_spot)
