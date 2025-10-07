from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketLinkedInstrument(ABC):
    """Base interface for instruments linked to market handles."""

    currency: str

    @abstractmethod
    def npv(self) -> float:
        """Return the present value for the current market state."""

    def __float__(self) -> float:  # pragma: no cover - convenience
        return float(self.npv())
