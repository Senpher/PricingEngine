from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
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


@dataclass(frozen=True, kw_only=True)
class CurveNodes:
    """
    Immutable container of curve *nodes* (not a curve itself).

    - dates: strictly increasing QuantLib Dates
    - quotes: per-date numbers matching quote_kind
        * "zero"     -> zero yields at those dates (per your comp/day-count convention)
        * "discount" -> discount factors in (0, 1]
        * "forward"  -> (rare) forward rates at those dates
    - day_counter: QuantLib DayCounter for year-fractions inside the YTS
    - as_of: evaluation date, metadata
    - role: how you intend to use it (discounting vs forecasting), just metadata
    """

    as_of: Date
    dates: Sequence[Date]
    quotes: Sequence[float]
    day_counter: DayCounter
    quote_kind: QuoteKind = "zero"
    role: CurveRole = "discounting"

    def __post_init__(self):
        if len(self.dates) == 0:
            raise ValueError("at least one node is required")
        if len(self.dates) != len(self.quotes):  # sanity by kind
            raise ValueError("dates and quotes must have the same length")
        for i in range(1, len(self.dates)):  # strictly increasing
            if not (self.dates[i] > self.dates[i - 1]):
                raise ValueError("dates must be strictly increasing")
        if self.quote_kind == "discount":
            if not all(0.0 < v <= 1.0 for v in self.quotes):
                raise ValueError("discount factors must lie in (0, 1]")

    @property
    def nodes(self) -> tuple[tuple[Date, float], ...]:
        return tuple((date, quote) for date, quote in zip(self.dates, self.quotes))

    @cached_property
    def yts_handle(self) -> YieldTermStructureHandle:
        """
        Build once and cache a QuantLib YieldTermStructureHandle for these nodes.
        Subsequent accesses reuse the same handle. (No relinking here.)
        """
        if self.quote_kind == "zero":
            if len(self.quotes) == 1:
                yts = FlatForward(
                    self.as_of,
                    QuoteHandle(SimpleQuote(self.quotes[0])),
                    self.day_counter,
                )
            else:
                yts = ZeroCurve(self.dates, self.quotes, self.day_counter)
        elif self.quote_kind == "discount":
            if len(self.quotes) < 2:
                raise ValueError("discount curve needs at least two discount nodes")
            dates = list(self.dates)
            discounts = list(self.quotes)
            if dates[0] != self.as_of:
                dates.insert(0, self.as_of)
                discounts.insert(0, 1.0)
            yts = DiscountCurve(dates, discounts, self.day_counter)
        elif self.quote_kind == "forward":
            if len(self.quotes) < 2:
                raise ValueError("forward curve needs at least two nodes")
            yts = ForwardCurve(self.dates, self.quotes, self.day_counter)
        elif self.quote_kind == "flat":
            if len(self.quotes) != 1:
                raise ValueError("quote_kind='flat' expects exactly one zero rate")
            yts = FlatForward(
                self.as_of, QuoteHandle(SimpleQuote(self.quotes[0])), self.day_counter
            )
        else:
            raise ValueError(f"Unsupported quote_kind: {self.quote_kind}")

        return YieldTermStructureHandle(yts)

    # nice alias for readability / compatibility
    def to_handle(self) -> YieldTermStructureHandle:
        return self.yts_handle

    # ---------- utilities ----------
    def discount_factor(self, date: Date) -> float:
        """Convenience: DF(as_of, date) via the cached handle."""
        return self.yts_handle.discount(date)

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
            return replace(
                self,
                as_of=self.as_of,
                dates=self.dates,
                quotes=new_quotes,
                day_counter=self.day_counter,
                quote_kind=self.quote_kind,
                role=self.role,
            )

        if self.quote_kind == "discount":
            new_discounts: list[float] = []
            for d, df in zip(self.dates, self.quotes):
                t = self.day_counter.yearFraction(self.as_of, d)
                if t <= 0.0:
                    new_discounts.append(df)  # protect as_of/near-0 times
                    continue
                r = -log(df) / t
                df_new = exp(-(r + bump_r) * t)
                new_discounts.append(df_new)
            return replace(
                self,
                as_of=self.as_of,
                dates=self.dates,
                quotes=tuple(new_discounts),
                day_counter=self.day_counter,
                quote_kind="discount",
                role=self.role,
            )

        if self.quote_kind == "forward":
            new_forwards = tuple(f + bump_r for f in self.quotes)
            return replace(
                self,
                as_of=self.as_of,
                dates=self.dates,
                quotes=new_forwards,
                day_counter=self.day_counter,
                quote_kind="forward",
                role=self.role,
            )

        # fallback (shouldn't hit due to earlier checks)
        return self

    # convenience alternate constructors
    @classmethod
    def from_zeros(
            cls,
            as_of: Date,
            dates: Sequence[Date],
            zeros: Sequence[float],
            day_counter: DayCounter,
            role: CurveRole = "discounting",
    ) -> CurveNodes:
        return cls(
            as_of=as_of,
            dates=dates,
            quotes=zeros,
            day_counter=day_counter,
            quote_kind="zero",
            role=role,
        )

    @classmethod
    def from_discounts(
            cls,
            as_of: Date,
            dates: Sequence[Date],
            discounts: Sequence[float],
            day_counter: DayCounter,
            role: CurveRole = "discounting",
    ) -> CurveNodes:
        return cls(
            as_of=as_of,
            dates=dates,
            quotes=discounts,
            day_counter=day_counter,
            quote_kind="discount",
            role=role,
        )

    @classmethod
    def from_forwards(
            cls,
            as_of: Date,
            dates: Sequence[Date],
            forwards: Sequence[float],
            day_counter: DayCounter,
            role: CurveRole = "forecasting",
    ) -> CurveNodes:
        """Convenience constructor for forward-rate curves."""
        return cls(
            as_of=as_of,
            dates=dates,
            quotes=forwards,
            day_counter=day_counter,
            quote_kind="forward",
            role=role,
        )

    @classmethod
    def from_flat(
            cls,
            as_of: Date,
            maturity: Date,
            zero: float,
            day_counter: DayCounter,
            role: CurveRole = "discounting",
    ) -> CurveNodes:
        """Flat zero-rate curve out to ``maturity``."""
        return cls(
            as_of=as_of,
            dates=[maturity],
            quotes=[zero],
            day_counter=day_counter,
            quote_kind="flat",
            role=role,
        )
