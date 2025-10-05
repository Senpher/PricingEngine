from abc import ABC, abstractmethod
import warnings


class Instrument(ABC):
    """Abstract base class for all priced Instruments."""

    @property
    @abstractmethod
    def is_expired(self) -> bool:
        """True if, by convention, the instrument should have zero value."""
        raise NotImplementedError

    @abstractmethod
    def npv(self, *args, **kwargs) -> float:
        """
        Present value in the instrument's pricing currency.

        Convention: subclasses are responsible for returning 0.0 when
        `self.is_expired` is True (so callers don’t need to check).
        """
        raise NotImplementedError

    # --- Backward compatibility alias ---
    def mark_to_market(self, *args, **kwargs) -> float:
        """
        Deprecated: use `npv(...)` instead.
        """
        warnings.warn(
            "Instrument.mark_to_market(...) is deprecated; use npv(...) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.npv(*args, **kwargs)
