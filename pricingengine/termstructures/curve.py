"""Minimal curve container used by the portfolio engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import QuantLib as ql


@dataclass(frozen=True)
class Curve:
    """Lightweight container for curve data points."""

    dates: Tuple[ql.Date, ...]
    day_counter: ql.DayCounter
    quotes: Tuple[float, ...]

    def __init__(
        self, *, dates: Sequence[ql.Date], day_counter: ql.DayCounter, quotes: Sequence[float]
    ) -> None:
        object.__setattr__(self, "dates", tuple(dates))
        object.__setattr__(self, "day_counter", day_counter)
        object.__setattr__(self, "quotes", tuple(quotes))

    def to_zero_curve(self) -> ql.ZeroCurve:
        """Build a QuantLib zero curve from the stored data."""

        return ql.ZeroCurve(list(self.dates), list(self.quotes), self.day_counter)
