from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, log
from typing import Literal, Sequence

from QuantLib import (
    Date,
    DayCounter,
    DiscountCurve,
    FlatForward,
    ForwardCurve,
    QuoteHandle,
    SimpleQuote,
    YieldTermStructureHandle,
    ZeroCurve,
)

QuoteKind = Literal["zero", "discount", "forward", "flat"]
CurveRole = Literal["discounting", "forecasting", "other"]


@dataclass(frozen=True, kw_only=True, slots=True)
class CurveNodes:
    """
    Immutable container of curve nodes (not the curve itself).

    - dates, quotes are normalized to tuples for immutability.
    - yts_handle(): lazy-builds + caches a QuantLib YieldTermStructureHandle.
    - bump(bp): returns a NEW CurveNodes with a parallel bp shift (zeros/flat/discount).
    """

    asof: Date
    dates: Sequence[Date]
    quotes: Sequence[float]
    day_count: DayCounter
    quote_kind: QuoteKind = "zero"
    role: CurveRole = "discounting"

    # cached handle (not part of identity/eq)
    _yts_handle: YieldTermStructureHandle | None = field(
        default=None, init=False, repr=False, compare=False
    )

    # ---------- lifecycle ----------
    def __post_init__(self):
        # materialize to tuples for immutability & predictable hashing/eq
        if not isinstance(self.dates, tuple):
            object.__setattr__(self, "dates", tuple(self.dates))
        if not isinstance(self.quotes, tuple):
            object.__setattr__(self, "quotes", tuple(float(q) for q in self.quotes))

        if len(self.dates) == 0:
            raise ValueError("at least one node is required")
        if len(self.dates) != len(self.quotes):
            raise ValueError("dates and quotes must have the same length")

        # strictly increasing dates
        for i in range(1, len(self.dates)):
            if not (self.dates[i] > self.dates[i - 1]):
                raise ValueError("dates must be strictly increasing")

        if self.quote_kind == "discount":
            if not all(0.0 < v <= 1.0 for v in self.quotes):
                raise ValueError("discount factors must lie in (0, 1]")

    # ---------- basic props ----------
    @property
    def nodes(self) -> tuple[tuple[Date, float], ...]:
        return tuple(zip(self.dates, self.quotes))

    # ---------- handle building (cached) ----------
    def yts_handle(self) -> YieldTermStructureHandle:
        """
        Build (once) and return a QuantLib YieldTermStructureHandle for these nodes.
        Subsequent calls return the cached handle.
        """
        h = self._yts_handle
        if h is not None:
            return h

        if self.quote_kind == "zero":
            if len(self.quotes) == 1:
                yts = FlatForward(
                    self.asof, QuoteHandle(SimpleQuote(self.quotes[0])), self.day_count
                )
            else:
                yts = ZeroCurve(self.dates, self.quotes, self.day_count)
        elif self.quote_kind == "discount":
            if len(self.quotes) < 2:
                raise ValueError("discount curve needs at least two discount nodes")
            dates = list(self.dates)
            discounts = list(self.quotes)
            if dates[0] != self.asof:
                dates.insert(0, self.asof)
                discounts.insert(0, 1.0)
            yts = DiscountCurve(dates, discounts, self.day_count)
        elif self.quote_kind == "forward":
            if len(self.quotes) < 2:
                raise ValueError("forward curve needs at least two nodes")
            yts = ForwardCurve(self.dates, self.quotes, self.day_count)
        elif self.quote_kind == "flat":
            if len(self.quotes) != 1:
                raise ValueError("quote_kind='flat' expects exactly one zero rate")
            yts = FlatForward(
                self.asof, QuoteHandle(SimpleQuote(self.quotes[0])), self.day_count
            )
        else:
            raise ValueError(f"Unsupported quote_kind: {self.quote_kind}")

        handle = YieldTermStructureHandle(yts)
        object.__setattr__(self, "_yts_handle", handle)  # cache in frozen dataclass
        return handle

    # nice alias for readability / compatibility
    def to_handle(self) -> YieldTermStructureHandle:
        return self.yts_handle()

    # ---------- utilities ----------
    def discount_factor(self, date: Date) -> float:
        """Convenience: DF(asof, date) via the cached handle."""
        return self.yts_handle().discount(date)

    def bump(self, bp: float) -> CurveNodes:
        """Return a new curve with a parallel bump of ``bp`` basis points.

        - For ``zero`` and ``flat`` curves, bp/1e4 is added to each rate.
        - For ``discount`` curves, DFs are converted to rates, bumped and
          converted back via ``exp(-(r + bump)*t)``.
        - For ``forward`` curves, forwards are simply shifted by bp/1e4.
        """
        bump_r = bp / 10_000.0

        if self.quote_kind in {"zero", "flat"}:
            new_quotes = tuple(q + bump_r for q in self.quotes)
            return type(self)(
                asof=self.asof,
                dates=self.dates,
                quotes=new_quotes,
                day_count=self.day_count,
                quote_kind=self.quote_kind,
                role=self.role,
            )

        if self.quote_kind == "discount":
            new_discounts: list[float] = []
            for d, df in zip(self.dates, self.quotes):
                t = self.day_count.yearFraction(self.asof, d)
                if t <= 0.0:
                    new_discounts.append(df)  # protect asof/near-0 times
                    continue
                r = -log(df) / t
                df_new = exp(-(r + bump_r) * t)
                new_discounts.append(df_new)
            return type(self)(
                asof=self.asof,
                dates=self.dates,
                quotes=tuple(new_discounts),
                day_count=self.day_count,
                quote_kind="discount",
                role=self.role,
            )

        if self.quote_kind == "forward":
            # simple parallel shift; you can refine to preserve integral properties
            new_forwards = tuple(f + bump_r for f in self.quotes)
            return type(self)(
                asof=self.asof,
                dates=self.dates,
                quotes=new_forwards,
                day_count=self.day_count,
                quote_kind="forward",
                role=self.role,
            )

        # fallback (shouldn't hit due to earlier checks)
        return self

    # backward compatibility: older code expected a `bump_zero_rates` method
    def bump_zero_rates(self, bp: float) -> CurveNodes:
        return self.bump(bp)

    # convenience alternate constructors
    @classmethod
    def from_zeros(
        cls,
        asof: Date,
        dates: Sequence[Date],
        zeros: Sequence[float],
        day_count: DayCounter,
        role: CurveRole = "discounting",
    ) -> CurveNodes:
        return cls(
            asof=asof,
            dates=dates,
            quotes=zeros,
            day_count=day_count,
            quote_kind="zero",
            role=role,
        )

    @classmethod
    def from_discounts(
        cls,
        asof: Date,
        dates: Sequence[Date],
        discounts: Sequence[float],
        day_count: DayCounter,
        role: CurveRole = "discounting",
    ) -> CurveNodes:
        return cls(
            asof=asof,
            dates=dates,
            quotes=discounts,
            day_count=day_count,
            quote_kind="discount",
            role=role,
        )

    @classmethod
    def from_forwards(
        cls,
        asof: Date,
        dates: Sequence[Date],
        forwards: Sequence[float],
        day_count: DayCounter,
        role: CurveRole = "forecasting",
    ) -> CurveNodes:
        """Convenience constructor for forward-rate curves."""
        return cls(
            asof=asof,
            dates=dates,
            quotes=forwards,
            day_count=day_count,
            quote_kind="forward",
            role=role,
        )

    @classmethod
    def from_flat(
        cls,
        asof: Date,
        maturity: Date,
        zero: float,
        day_count: DayCounter,
        role: CurveRole = "discounting",
    ) -> CurveNodes:
        """Flat zero-rate curve out to ``maturity``."""
        return cls(
            asof=asof,
            dates=[maturity],
            quotes=[zero],
            day_count=day_count,
            quote_kind="flat",
            role=role,
        )
