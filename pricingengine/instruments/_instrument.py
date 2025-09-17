from abc import ABC, abstractmethod


class Instrument(ABC):
    """Abstract base class for all instrument objects."""

    @property
    @abstractmethod
    def is_expired(self) -> bool:
        pass

    @abstractmethod
    def mark_to_market(self, *args, **kwargs) -> R:
        if self.is_expired:
            return 0.0
        else:
            pass
