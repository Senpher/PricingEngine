from __future__ import annotations

from abc import ABC, abstractmethod


class Instrument(ABC):
    """Abstract base class for all tradable instruments."""

    @abstractmethod
    def is_expired(self) -> bool:
        """Whether the instrument has passed its maturity."""
        raise NotImplementedError

    @abstractmethod
    def mtm(self, *args, **kwargs) -> float:
        """Mark-to-market value of the instrument."""
        raise NotImplementedError

    def price(self, *args, **kwargs) -> float:
        """Convenience alias that delegates to :meth:`mtm`."""
        return self.mtm(*args, **kwargs)
