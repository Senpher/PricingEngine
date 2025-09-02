from __future__ import annotations

from abc import ABC, abstractmethod


class Instrument(ABC):

    @abstractmethod
    def price(self, *args, **kwargs) -> float:
        pass
