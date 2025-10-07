from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from PricingEngine.Instruments.Common import Instrument
from .context import MarketContext


@dataclass
class Position:
    name: str
    instrument: Instrument  # All instruments must inherit from Instrument and implement npv(ctx)
    currency: Optional[str] = None
    underlying: Optional[str] = None
    trade_id: Optional[str] = None
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
            return sum(p.instrument.npv(ctx) for p in self.positions)
