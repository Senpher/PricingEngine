"""Shared instrument interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class RiskResult:
    """Container for simple risk measures.

    Only a couple of common Greeks are provided for now; extend as needed.
    """

    dv01: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None


class Instrument(ABC):
    """Abstract base class for priced instruments."""

    @abstractmethod
    def price(self, *args, **kwargs) -> float:
        """Return a price for the instrument."""

    @abstractmethod
    def mtm(self, *args, **kwargs) -> float:
        """Alias for the mark-to-market (NPV) price."""
