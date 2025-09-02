from __future__ import annotations

from abc import ABC, abstractmethod


class Instrument(ABC):
    """Abstract base for all financial instruments."""

    @abstractmethod
    def price(self, *args, **kwargs) -> float:
        """Return the price or present value of the instrument."""
        raise NotImplementedError
