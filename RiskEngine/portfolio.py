from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .instruments.base import MarketLinkedInstrument


@dataclass(frozen=True)
class Position:
    """A portfolio position referencing a market-linked instrument."""

    name: str
    instrument: MarketLinkedInstrument
    weight: float = 1.0

    def npv(self) -> float:
        return float(self.instrument.npv()) * float(self.weight)

    @property
    def currency(self) -> str:
        return self.instrument.currency


@dataclass(frozen=True)
class PortfolioValuation:
    totals_by_currency: dict[str, float]
    position_pvs: dict[str, float]

    def total(self, base_currency: str) -> float:
        if base_currency in self.totals_by_currency:
            return self.totals_by_currency[base_currency]
        if len(self.totals_by_currency) == 1:
            return next(iter(self.totals_by_currency.values()))
        raise ValueError("Cannot infer portfolio total in base currency; missing FX conversion logic.")


@dataclass
class Portfolio:
    """Collection of positions valued off a shared market context."""

    positions: list[Position]
    base_currency: str

    def __init__(self, positions: Iterable[Position], base_currency: str) -> None:
        self.positions = list(positions)
        self.base_currency = base_currency

    def valuation(self) -> PortfolioValuation:
        totals: dict[str, float] = {}
        per_position: dict[str, float] = {}
        for position in self.positions:
            pv = position.npv()
            per_position[position.name] = pv
            totals[position.currency] = totals.get(position.currency, 0.0) + pv
        return PortfolioValuation(totals_by_currency=totals, position_pvs=per_position)
