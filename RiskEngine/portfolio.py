from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PricingEngine.Instruments.Common import Instrument

from .context import MarketContext


@dataclass
class Position:
    name: str
    instrument: Instrument  # All instruments must inherit from Instrument and implement npv(ctx)
    currency: str | None = None
    underlying: str | None = None
    trade_id: str | None = None
    # Add more metadata as needed for reporting or instrument construction


class Portfolio:
    def __init__(self, positions: Iterable[Position] = ()):  # Support empty init
        self.positions = list(positions)

    def add_position(self, position: Position):
        self.positions.append(position)

    def add_positions(self, positions: Iterable[Position]):
        self.positions.extend(positions)

    def price(self, ctx: MarketContext) -> float:
        with ctx.at_eval():
            total = 0.0
            for position in self.positions:
                instrument = position.instrument
                try:
                    total += instrument.npv(ctx)
                except TypeError:
                    total += instrument.npv()
            return total
